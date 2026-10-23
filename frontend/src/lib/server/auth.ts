import { APIError } from "better-auth/api";
import { createHash, createHmac, randomUUID, timingSafeEqual } from "node:crypto";
import { headers } from "next/headers";
import { NextResponse } from "next/server";

import { better, origin, authDatabase } from "./better-auth";
import { redis, withSessionLock } from "./session-store";

export type EduviaSession = { user: { sub: string; email: string; name: string; email_verified: boolean }; eduviaId: string; csrf: string; token: string; createdAt: Date };
import { HttpError } from "./http-error";
export { HttpError } from "./http-error";
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
export async function backend(request: Request, path: string, method = "GET") {
  return lockedSession(async session => {
    if (method !== "GET") checkCsrf(request, session);
    const { token } = await better().api.getToken({ headers: await headers() });
    await requireSession();
    const response = await fetch(new URL(path, process.env.API_INTERNAL_URL || "http://127.0.0.1:8000"), { method, headers: { Authorization: `Bearer ${token}`, Accept: "application/json" }, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(5000) });
    return NextResponse.json(await response.json(), { status: response.status, headers: { "Cache-Control": "no-store" } });
  });
}
