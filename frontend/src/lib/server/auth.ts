import { randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import { Auth0Client } from "@auth0/nextjs-auth0/server";
import { AccessTokenError, AccessTokenErrorCode } from "@auth0/nextjs-auth0/errors";
import type { SessionData } from "@auth0/nextjs-auth0/types";
import { NextResponse } from "next/server";
import { sessionStore, withSessionLock } from "./session-store";

let instance: Auth0Client | undefined;
export function appOrigin() {
  const url = new URL(process.env.APP_BASE_URL || "http://127.0.0.1:3000");
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash || !["http:", "https:"].includes(url.protocol)) throw new Error("invalid_app_origin");
  if (process.env.NODE_ENV === "production" && url.protocol !== "https:" && !["localhost", "127.0.0.1"].includes(url.hostname)) throw new Error("https_required");
  return url.origin;
}
export function auth() {
  if (!instance) {
    for (const name of ["AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET", "AUTH0_SECRET", "AUTH0_AUDIENCE", "SESSION_REDIS_URL", "SESSION_ENCRYPTION_KEY"]) {
      if (!process.env[name]) throw new Error("auth_unconfigured");
    }
    instance = new Auth0Client({
      appBaseUrl: appOrigin(),
      authorizationParameters: { audience: process.env.AUTH0_AUDIENCE, scope: "openid profile email offline_access", connection: process.env.AUTH0_CONNECTION || "Username-Password-Authentication" },
      sessionStore,
      enableAccessTokenEndpoint: false,
      session: { rolling: false, absoluteDuration: 86400, inactivityDuration: 7200, cookie: { name: "eduvia_session", sameSite: "lax", secure: appOrigin().startsWith("https:") } },
      httpTimeout: 5000,
      includeIdTokenHintInOIDCLogoutUrl: false,
      allowInsecureRequests: process.env.AUTH_TEST_MODE === "1" && process.env.NODE_ENV !== "production",
      beforeSessionSaved: async session => ({ ...session, eduviaId: session.eduviaId || randomUUID(), csrf: session.csrf || randomBytes(32).toString("hex") }),
      onCallback: async (error, _context, session) => {
        if (error || !session) {
          const safeCode = (value: unknown) => typeof value === "string" && /^[a-zA-Z0-9_-]{1,100}$/.test(value) ? value : undefined;
          const cause = error?.cause as { code?: unknown; error?: unknown } | undefined;
          console.error(JSON.stringify({ event: "auth_callback_failed", requestId: randomUUID(), code: safeCode(error?.code), causeCode: safeCode(cause?.code), oauthError: safeCode(cause?.error), missingSession: !session }));
          return NextResponse.redirect(new URL("/login?error=callback", appOrigin()));
        }
        return NextResponse.redirect(new URL(session.user.email_verified === true ? "/onboarding" : "/verify-email", appOrigin()));
      },
    });
  }
  return instance;
}
export class HttpError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}
export function failure(error: unknown) {
  const known = error instanceof HttpError;
  const status = known ? error.status : 503;
  const code = known ? error.code : "service_unavailable";
  const requestId = randomUUID();
  console.warn(JSON.stringify({ event: "auth_request_failed", code, requestId, type: error instanceof Error ? error.name : "unknown", ...(process.env.AUTH_TEST_MODE === "1" && error instanceof Error ? { frames: error.stack?.split("\n").slice(1, 4) } : {}) }));
  return NextResponse.json({ error: { code, message: known ? error.message : "Dịch vụ tạm thời không khả dụng. Vui lòng thử lại." }, requestId }, { status, headers: { "Cache-Control": "no-store", "X-Request-ID": requestId } });
}
export async function requireSession(verified = true): Promise<SessionData> {
  const session = await auth().getSession();
  if (!session) throw new HttpError(401, "unauthorized", "Vui lòng đăng nhập lại.");
  if (verified && session.user.email_verified !== true) throw new HttpError(403, "email_unverified", "Vui lòng xác minh email.");
  return session;
}
export function checkCsrf(request: Request, session: SessionData) {
  const expected = typeof session.csrf === "string" ? session.csrf : "";
  const actual = request.headers.get("x-csrf-token") || "";
  if (request.headers.get("origin") !== appOrigin() || !expected || Buffer.byteLength(actual) !== Buffer.byteLength(expected) || !timingSafeEqual(Buffer.from(actual), Buffer.from(expected))) {
    throw new HttpError(403, "csrf_failed", "Yêu cầu không hợp lệ.");
  }
}
export async function lockedSession<T>(action: (session: SessionData) => Promise<T>, verified = true) {
  const initial = await requireSession(verified);
  if (typeof initial.eduviaId !== "string") throw new HttpError(401, "unauthorized", "Vui lòng đăng nhập lại.");
  return withSessionLock(initial.eduviaId, async () => {
    const fresh = await requireSession(verified);
    if (fresh.eduviaId !== initial.eduviaId) throw new HttpError(401, "unauthorized", "Phiên đã thay đổi.");
    return action(fresh);
  });
}
export type BackendOptions = {
  /** JSON string, or a raw stream/Blob for uploads. Never forwarded for GET. */
  body?: BodyInit | null;
  /** Already-allowlisted headers only (see pickUploadHeaders). Authorization/Accept cannot be overridden. */
  headers?: Record<string, string>;
  /** Relay upstream status and tolerate non-JSON bodies instead of failing with 503. */
  passthroughStatus?: boolean;
};
export async function backend(request: Request, path: string, method = "GET", options: BackendOptions = {}) {
  const hasBody = options.body !== undefined && options.body !== null;
  if (method === "GET" && hasBody) throw new HttpError(500, "invalid_backend_call", "Yêu cầu không hợp lệ.");
  const call = await lockedSession(async session => {
    if (method !== "GET") checkCsrf(request, session);
    let token: string;
    try { token = (await auth().getAccessToken()).token; }
    catch (error) {
      if (error instanceof AccessTokenError && (
        [AccessTokenErrorCode.MISSING_SESSION, AccessTokenErrorCode.MISSING_REFRESH_TOKEN, AccessTokenErrorCode.SESSION_EXPIRED].includes(error.code as AccessTokenErrorCode) || error.cause?.code === "invalid_grant"
      )) throw new HttpError(401, "session_expired", "Phiên đã hết hạn. Vui lòng đăng nhập lại.");
      throw new HttpError(503, "refresh_unavailable", "Chưa thể gia hạn phiên. Vui lòng thử lại.");
    }
    // Re-read after refresh; never save the stale tokenSet read before getAccessToken.
    await auth().updateSession(await requireSession());
    const base = new URL(process.env.API_INTERNAL_URL || "http://127.0.0.1:8000");
    if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password) throw new Error("invalid_backend_origin");
    const send = async () => {
      // Caller headers first so they can never replace Authorization/Accept.
      const headers: Record<string, string> = { ...options.headers, Authorization: `Bearer ${token}`, Accept: "application/json" };
      const init: RequestInit & { duplex?: "half" } = { method, headers, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(hasBody ? 120000 : 5000) };
      if (hasBody) { init.body = options.body; if (typeof options.body !== "string") init.duplex = "half"; }
      return respond(await fetch(new URL(path, base), init), options.passthroughStatus === true);
    };
    // Long uploads must not hold the per-session lock: it would stall /api/session and other BFF calls.
    return hasBody ? send : await send();
  });
  return typeof call === "function" ? call() : call;
}
async function respond(response: Response, tolerant: boolean) {
  const headers = { "Cache-Control": "no-store" };
  if (response.status === 204 || response.status === 205) return new NextResponse(null, { status: response.status, headers });
  let payload: unknown;
  try { payload = await response.json(); }
  catch (error) {
    if (!tolerant) throw error;
    payload = { error: { code: "upstream_error", message: "Dịch vụ tạm thời không khả dụng. Vui lòng thử lại." }, requestId: randomUUID() };
  }
  return NextResponse.json(payload, { status: response.status, headers });
}
