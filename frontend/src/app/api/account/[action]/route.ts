import { allowEmail } from "@/lib/server/email-limit";
import { NextResponse } from "next/server";
import { better, betterEnabled, decryptStorage } from "@/lib/server/better-auth";
import { checkCsrf, failure, HttpError, lockedSession } from "@/lib/server/auth";
import { accountKey, methods, requireRecent, revokeAll, markSecurityChange } from "@/lib/server/account-center";
import { redis } from "@/lib/server/session-store";

export async function POST(request: Request, { params }: { params: Promise<{ action: string }> }) {
  if (!betterEnabled()) return new Response(null, { status: 404 });
  try { return await lockedSession(async session => {
    checkCsrf(request, session);
    const { action } = await params, connection = await redis();
    const enabled = await methods(session.user.sub);
    if (action === "reauthenticate") {
      const count = Number(await connection.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n", { keys: [accountKey(session.user.sub, "attempts")], arguments: [] }));
      if (count > 5) throw new HttpError(429, "rate_limited", "Vui lòng thử lại sau.");
      const { password } = await request.json();
      if (typeof password !== "string" || password.length > 128) throw new HttpError(400, "invalid_request", "Mật khẩu không hợp lệ.");
      await better().api.verifyPassword({ headers: request.headers, body: { password } });
      await connection.set(accountKey(session.user.sub, "reauth"), session.eduviaId, { EX: 300 });
      return NextResponse.json({ verified: true }, { headers: { "Cache-Control": "no-store" } });
    }
    if (action === "password") {
      if (!await allowEmail("request-password-reset", session.user.email)) throw new HttpError(429, "rate_limited", "Vui lòng chờ trước khi gửi lại email.");
      await better().api.requestPasswordReset({ body: { email: session.user.email, redirectTo: "/reset-password" }, headers: request.headers });
      return NextResponse.json({ accepted: true }, { status: 202, headers: { "Cache-Control": "no-store" } });
    }
    await requireRecent();
    if (action === "link-google") {
      if (enabled.google) throw new HttpError(409, "identity_conflict", "Google đã được liên kết.");
      await connection.set(accountKey(session.user.sub, "link"), session.eduviaId, { EX: 300 });
      return better().api.linkSocialAccount({ headers: request.headers, body: { provider: "google", callbackURL: "/account/complete", errorCallbackURL: "/account?error=link", disableRedirect: true }, asResponse: true });
    }
    if (action === "confirm-google") {
      const pendingKey = accountKey(session.user.sub, "pending");
      const packed = await connection.getDel(pendingKey);
      if (!packed) throw new HttpError(409, "link_expired", "Yêu cầu liên kết đã hết hạn.");
      const pending = JSON.parse(decryptStorage(pendingKey, packed)) as { accountId: string; sessionId: string };
      if (pending.sessionId !== session.eduviaId || enabled.google) throw new HttpError(409, "identity_conflict", "Yêu cầu liên kết không hợp lệ.");
      await markSecurityChange(session.user.sub);
      await connection.set(accountKey(session.user.sub, "approved"), pending.accountId, { EX: 10 });
      try {
        const context = await better().$context;
        await context.internalAdapter.createAccount({ providerId: "google", accountId: pending.accountId, userId: session.user.sub });
      } finally { await connection.del(accountKey(session.user.sub, "approved")); }
      const loggedOut = await revokeAll(session.user.sub);
      const response = NextResponse.json({ redirect: "/login" }, { headers: { "Cache-Control": "no-store" } });
      for (const cookie of loggedOut.headers.getSetCookie()) response.headers.append("set-cookie", cookie);
      return response;
    }
    if (action === "unlink-google") {
      if (!enabled.password || !enabled.google) throw new HttpError(409, "last_login_method", "Cần giữ ít nhất một cách đăng nhập sử dụng được.");
      await markSecurityChange(session.user.sub);
      await better().api.unlinkAccount({ headers: request.headers, body: { accountId: enabled.googleAccountId! } });
      await connection.del(accountKey(session.user.sub, "reauth"));
      const loggedOut = await revokeAll(session.user.sub);
      const response = NextResponse.json({ redirect: "/login" }, { headers: { "Cache-Control": "no-store" } });
      for (const cookie of loggedOut.headers.getSetCookie()) response.headers.append("set-cookie", cookie);
      return response;
    }
    throw new HttpError(404, "not_found", "Không tìm thấy thao tác.");
  }); } catch (error) { return failure(error); }
}
