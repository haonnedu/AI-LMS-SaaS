import { APIError } from "better-auth/api";
import { createHash, createHmac, randomUUID, timingSafeEqual } from "node:crypto";
import { AccessTokenError, AccessTokenErrorCode } from "@auth0/nextjs-auth0/errors";
import { headers } from "next/headers";
import { NextResponse } from "next/server";
import * as legacy from "./legacy-auth";
import { better, betterEnabled, origin, authDatabase } from "./better-auth";
import { redis, withSessionLock } from "./session-store";
export const auth = legacy.auth;
export const appOrigin = legacy.appOrigin;
export type EduviaSession = { user: { sub: string; email: string; name: string; email_verified: boolean }; eduviaId: string; csrf: string; token: string; createdAt: Date };
export const HttpError = legacy.HttpError;
export function failure(error: unknown) {
  if (error instanceof APIError && error.statusCode >= 400 && error.statusCode < 500) {
    const status = error.statusCode;
    error = new HttpError(status, status === 429 ? "rate_limited" : status === 409 ? "identity_conflict" : "authentication_failed", "Không thể xác thực hoặc hoàn thành thao tác. Vui lòng thử lại.");
  }
  const known = error instanceof HttpError ? error : null;
  const status = known ? known.status : 503;
  const code = known ? known.code : "service_unavailable";
  const requestId = randomUUID();
  console.warn(JSON.stringify({ event: "auth_request_failed", code, requestId, type: error instanceof Error ? error.name : "unknown", ...(process.env.AUTH_TEST_MODE === "1" && error instanceof Error ? { frames: error.stack?.split("\n").slice(1, 4) } : {}) }));
  return NextResponse.json({ error: { code, message: known ? known.message : "Dịch vụ tạm thời không khả dụng. Vui lòng thử lại." }, requestId }, { status, headers: { "Cache-Control": "no-store", "X-Request-ID": requestId } });
}

export async function requireSession(verified = true): Promise<EduviaSession> {
  if (!betterEnabled()) {
    const old = await legacy.requireSession(verified);
    return { user: { sub: old.user.sub, email: old.user.email || "", name: old.user.name || "", email_verified: old.user.email_verified === true }, eduviaId: String(old.eduviaId), csrf: String(old.csrf), token: "", createdAt: new Date(old.internal.createdAt * 1000) };
  }
  await redis();
  const current = await better().api.getSession({ headers: await headers(), query: { disableCookieCache: true } });
  if (!current || Date.now() - new Date(current.session.createdAt).getTime() >= 86400000) throw new HttpError(401, "unauthorized", "Vui lòng đăng nhập lại.");
  const durable = await authDatabase().query("SELECT revoked_before FROM auth.session_revocations WHERE user_id=$1", [current.user.id]);
  if (durable.rows[0] && new Date(current.session.createdAt).getTime() <= new Date(durable.rows[0].revoked_before).getTime()) throw new HttpError(401, "unauthorized", "Phiên đã kết thúc. Vui lòng đăng nhập lại.");
  const revokedBefore = await (await redis()).get("eduvia:ba:user-revoked-before:" + createHash("sha256").update(current.user.id).digest("hex"));
  if (revokedBefore && new Date(current.session.createdAt).getTime() <= Number(revokedBefore)) throw new HttpError(401, "unauthorized", "Phiên đã kết thúc. Vui lòng đăng nhập lại.");
  if (verified && !current.user.emailVerified) throw new HttpError(403, "email_unverified", "Vui lòng xác minh email.");
  return { user: { sub: current.user.id, email: current.user.email, name: current.user.name, email_verified: current.user.emailVerified }, eduviaId: current.session.id,
    csrf: createHmac("sha256", process.env.BETTER_AUTH_SECRET!).update("csrf:" + current.session.id).digest("hex"), token: current.session.token, createdAt: current.session.createdAt };
}
export function checkCsrf(request: Request, session: { csrf?: unknown }) {
  const expected = typeof session.csrf === "string" ? session.csrf : "", actual = request.headers.get("x-csrf-token") || "";
  if (request.headers.get("origin") !== origin() || !expected || Buffer.byteLength(expected) !== Buffer.byteLength(actual) || !timingSafeEqual(Buffer.from(expected), Buffer.from(actual))) throw new HttpError(403, "csrf_failed", "Yêu cầu không hợp lệ.");
}
export async function lockedSession<T>(action: (session: Awaited<ReturnType<typeof requireSession>>) => Promise<T>, verified = true) {
  const initial = await requireSession(verified);
  return withSessionLock(String(initial.eduviaId), async () => {
    const fresh = await requireSession(verified);
    if (fresh.eduviaId !== initial.eduviaId) throw new HttpError(401, "unauthorized", "Phiên đã thay đổi.");
    return action(fresh);
  });
}
export type BackendOptions = { body?: BodyInit | null; headers?: Record<string, string>; passthroughStatus?: boolean };

/** Provider-agnostic API bearer token for the current session (legacy Auth0 or Better Auth). */
export async function accessToken(): Promise<string> {
  if (!betterEnabled()) {
    let token: string;
    try { token = (await legacy.auth().getAccessToken()).token; }
    catch (error) {
      if (error instanceof AccessTokenError && (
        [AccessTokenErrorCode.MISSING_SESSION, AccessTokenErrorCode.MISSING_REFRESH_TOKEN, AccessTokenErrorCode.SESSION_EXPIRED].includes(error.code as AccessTokenErrorCode) || error.cause?.code === "invalid_grant"
      )) throw new HttpError(401, "session_expired", "Phiên đã hết hạn. Vui lòng đăng nhập lại.");
      throw new HttpError(503, "refresh_unavailable", "Chưa thể gia hạn phiên. Vui lòng thử lại.");
    }
    // Re-read after refresh; never save the stale tokenSet read before getAccessToken.
    await legacy.auth().updateSession(await legacy.requireSession());
    return token;
  }
  const { token } = await better().api.getToken({ headers: await headers() });
  await requireSession();
  return token;
}
export function backendOrigin() {
  const base = new URL(process.env.API_INTERNAL_URL || "http://127.0.0.1:8000");
  if (!["http:", "https:"].includes(base.protocol) || base.username || base.password) throw new Error("invalid_backend_origin");
  return base;
}
/**
 * Forwards a same-origin BFF request to the API with the session's bearer token.
 * CSRF (Origin + token) is enforced for every non-GET before any upstream work. `options.body`
 * forwards a JSON string or a streamed raw body (uploads); only caller headers in `options.headers`
 * are sent and they can never replace Authorization/Accept. Long uploads release the per-session
 * lock before streaming so /api/session and other BFF calls are not stalled.
 */
export async function backend(request: Request, path: string, method = "GET", options: BackendOptions = {}) {
  const hasBody = options.body !== undefined && options.body !== null;
  if (method === "GET" && hasBody) throw new HttpError(500, "invalid_backend_call", "Yêu cầu không hợp lệ.");
  const call = await lockedSession(async session => {
    if (method !== "GET") checkCsrf(request, session);
    const token = await accessToken();
    const base = backendOrigin();
    const send = async () => {
      const requestHeaders: Record<string, string> = { ...options.headers, Authorization: `Bearer ${token}`, Accept: "application/json" };
      const init: RequestInit & { duplex?: "half" } = { method, headers: requestHeaders, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(hasBody ? 120000 : 5000) };
      if (hasBody) { init.body = options.body; if (typeof options.body !== "string") init.duplex = "half"; }
      return respond(await fetch(new URL(path, base), init), options.passthroughStatus === true);
    };
    return hasBody ? send : await send();
  });
  return typeof call === "function" ? call() : call;
}
async function respond(response: Response, tolerant: boolean) {
  const responseHeaders = { "Cache-Control": "no-store" };
  if (response.status === 204 || response.status === 205) return new NextResponse(null, { status: response.status, headers: responseHeaders });
  let payload: unknown;
  try { payload = await response.json(); }
  catch (error) {
    if (!tolerant) throw error;
    payload = { error: { code: "upstream_error", message: "Dịch vụ tạm thời không khả dụng. Vui lòng thử lại." }, requestId: randomUUID() };
  }
  return NextResponse.json(payload, { status: response.status, headers: responseHeaders });
}
