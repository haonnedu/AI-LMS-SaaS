import { createHash } from "node:crypto";
import { NextResponse } from "next/server";
import { checkCsrf, failure, HttpError, lockedSession } from "@/lib/server/auth";
import { redis } from "@/lib/server/session-store";
export async function POST(request: Request) {
  try {
    return await lockedSession(async session => {
      checkCsrf(request, session);
      if (session.user.email_verified === true) return NextResponse.json({ accepted: true }, { status: 202, headers: { "Cache-Control": "no-store" } });
      const clientId = process.env.AUTH0_MANAGEMENT_CLIENT_ID;
      const secret = process.env.AUTH0_MANAGEMENT_CLIENT_SECRET;
      if (!clientId || !secret) throw new Error("verification_unconfigured");
      const identity = createHash("sha256").update(process.env.AUTH0_DOMAIN + ":" + session.user.sub).digest("hex");
      const allowed = await (await redis()).eval(`
        local now=tonumber(ARGV[1]); redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',now-3600000)
        local latest=redis.call('ZREVRANGE',KEYS[1],0,0,'WITHSCORES')
        if (#latest>0 and now-tonumber(latest[2])<60000) or redis.call('ZCARD',KEYS[1])>=5 then return 0 end
        redis.call('ZADD',KEYS[1],now,ARGV[1]); redis.call('EXPIRE',KEYS[1],3600); return 1`,
        { keys: ["eduvia:verify:" + identity], arguments: [String(Date.now())] });
      if (allowed !== 1) throw new HttpError(429, "rate_limited", "Vui lòng chờ trước khi gửi lại email.");
      const configured = process.env.AUTH0_DOMAIN!;
      const endpoint = new URL(configured.includes("://") ? configured : "https://" + configured);
      const localTest = process.env.AUTH_TEST_MODE === "1" && process.env.NODE_ENV !== "production" && endpoint.hostname === "localhost";
      if ((endpoint.protocol !== "https:" && !localTest) || endpoint.username || endpoint.password || endpoint.search || endpoint.hash || endpoint.pathname !== "/") throw new Error("invalid_identity_origin");
      const origin = endpoint.origin;
      const tokenResponse = await fetch(origin + "/oauth/token", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ grant_type: "client_credentials", client_id: clientId, client_secret: secret, audience: origin + "/api/v2/" }), signal: AbortSignal.timeout(4000), cache: "no-store", redirect: "error" });
      if (!tokenResponse.ok) throw new Error("verification_unavailable");
      const token = await tokenResponse.json();
      const response = await fetch(origin + "/api/v2/jobs/verification-email", { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token.access_token}` }, body: JSON.stringify({ user_id: session.user.sub, client_id: process.env.AUTH0_CLIENT_ID }), signal: AbortSignal.timeout(4000), cache: "no-store", redirect: "error" });
      if (!response.ok) throw new Error("verification_unavailable");
      return NextResponse.json({ accepted: true }, { status: 202, headers: { "Cache-Control": "no-store" } });
    }, false);
  } catch (error) { return failure(error); }
}
