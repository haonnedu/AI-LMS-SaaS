import { allowEmail } from "@/lib/server/email-limit";
import { better, betterEnabled, origin } from "@/lib/server/better-auth";
import { failure, HttpError } from "@/lib/server/auth";

const posts = new Set(["sign-in/email", "sign-up/email", "sign-in/social", "request-password-reset", "reset-password", "send-verification-email"]);
const gets = new Set(["jwks", "verify-email", "reset-password"]);
async function handle(request: Request) {
  try {
    if (!betterEnabled()) return new Response(null, { status: 404 });
    const path = new URL(request.url).pathname.slice("/api/auth/".length);
    const callback = /^callback\/google$/.test(path);
    if (request.method === "POST") {
      if (!posts.has(path) || request.headers.get("origin") !== origin()) throw new HttpError(403, "invalid_request", "Yêu cầu không hợp lệ.");
      if (!request.headers.get("content-type")?.startsWith("application/json")) throw new HttpError(415, "invalid_request", "Yêu cầu JSON.");
      const body = await request.clone().json().catch(() => { throw new HttpError(400, "invalid_request", "JSON không hợp lệ."); });
      if (["send-verification-email", "request-password-reset"].includes(path)) {
        if (typeof body.email !== "string" || body.email.length > 255) throw new HttpError(400, "invalid_request", "Email không hợp lệ.");
        if (!await allowEmail(path, body.email)) throw new HttpError(429, "rate_limited", "Vui lòng chờ trước khi gửi lại email.");
      }
      if (path === "reset-password") {
        const token = body.token || new URL(request.url).searchParams.get("token");
        if (typeof token === "string") {
          const context = await better().$context;
          const verification = await context.internalAdapter.findVerificationValue("reset-password:" + token);
          if (verification && new Date(verification.expiresAt).getTime() > Date.now()) {
            const { markSecurityChange } = await import("@/lib/server/account-center");
            await markSecurityChange(verification.value);
          }
        }
      }
      // This public surface cannot accept a provider ID token or link an identity.
      if (body.idToken || body.link || (path === "sign-in/social" && body.provider !== "google")) throw new HttpError(400, "invalid_request", "Yêu cầu không hợp lệ.");
      for (const key of ["callbackURL", "errorCallbackURL", "newUserCallbackURL", "redirectTo"]) {
        if (body[key] && !["/login", "/onboarding", "/verify-email", "/reset-password"].includes(body[key])) throw new HttpError(400, "invalid_redirect", "Đường dẫn không hợp lệ.");
      }
    } else if (!gets.has(path) && !callback && !path.startsWith("reset-password/")) return new Response(null, { status: 404 });
    const response = await better().handler(request);
    if (callback) {
      const current = await better().api.getSession({ headers: request.headers });
      if (current) {
        const { accountKey } = await import("@/lib/server/account-center");
        const { redis } = await import("@/lib/server/session-store");
        if (await (await redis()).exists(accountKey(current.user.id, "pending"))) return Response.redirect(new URL("/account?confirm=google", origin()));
      }
    }
    if (callback && response.status >= 400) return Response.redirect(new URL("/login?error=callback", origin()));
    const headers = new Headers(response.headers);
    headers.set("Cache-Control", "no-store"); headers.delete("set-auth-jwt"); headers.delete("content-length");
    if (response.status >= 300 && response.status < 400) return new Response(null, { status: response.status, headers });
    if (headers.get("content-type")?.includes("application/json")) {
      const payload = await response.json();
      if (path === "jwks" && response.ok) return Response.json(payload, { status: response.status, headers });
      if (!response.ok) {
        const code = typeof payload.code === "string" && /^[A-Z0-9_]{1,100}$/i.test(payload.code) ? payload.code.toLowerCase() : "authentication_failed";
        return failure(new HttpError(response.status, code, code === "email_not_verified" ? "Vui lòng xác minh email rồi đăng nhập lại." : "Thông tin không hợp lệ hoặc thao tác chưa hoàn tất."));
      }
      return Response.json({ accepted: true, ...(typeof payload.url === "string" ? { url: payload.url, redirect: payload.redirect === true } : {}) }, { status: response.status, headers });
    }
    return new Response(response.body, { status: response.status, headers });
  } catch (error) { return failure(error); }
}
export const GET = handle;
export const POST = handle;
