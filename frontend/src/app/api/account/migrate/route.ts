import { randomUUID } from "node:crypto";
import { NextResponse } from "next/server";
import { better, betterEnabled, origin } from "@/lib/server/better-auth";
import { auth as legacyAuth } from "@/lib/server/legacy-auth";
import { checkCsrf, failure, HttpError, lockedSession } from "@/lib/server/auth";
import { revokeAll, markSecurityChange } from "@/lib/server/account-center";

export async function POST(request: Request) {
  if (!betterEnabled() || process.env.AUTH0_MIGRATION_ENABLED !== "1") return new Response(null, { status: 404 });
  try { return await lockedSession(async target => {
    checkCsrf(request, target);
    const source = await legacyAuth().getSession();
    if (!source || source.user.email_verified !== true || Date.now() / 1000 - source.internal.createdAt > 300 || source.user.email?.toLowerCase() !== target.user.email.toLowerCase()) throw new HttpError(403, "migration_reauthentication_required", "Xác thực lại Auth0 cũ và dùng cùng email trong vòng 5 phút.");
    const domain = process.env.AUTH0_DOMAIN!;
    const sourceIssuer = new URL(domain.includes("://") ? domain : "https://" + domain).origin + "/";
    const proof = await better().api.signJWT({ body: {
      payload: { sub: target.user.sub, iat: Math.floor(Date.now() / 1000), purpose: "identity_transfer", jti: randomUUID(), source_issuer: sourceIssuer, source_subject: source.user.sub },
      overrideOptions: { jwt: { issuer: origin() + "/migration", audience: (process.env.BETTER_AUTH_AUDIENCE || "https://eduvia-api") + "/migration", expirationTime: "5m" } },
    } });
    const { token } = await better().api.getToken({ headers: request.headers });
    await markSecurityChange(target.user.sub);
    const result = await fetch(new URL("/v1/auth/migrate", process.env.API_INTERNAL_URL || "http://127.0.0.1:8000"), { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ proof: proof.token }), cache: "no-store", redirect: "error", signal: AbortSignal.timeout(5000) });
    if (!result.ok) return NextResponse.json(await result.json(), { status: result.status, headers: { "Cache-Control": "no-store" } });
    // The legacy SDK logout clears its Redis record and cookie; logout URL is followed by the browser.
    const { NextRequest } = await import("next/server");
    const oldLogout = await legacyAuth().middleware(new NextRequest(new URL("/auth/logout?returnTo=" + encodeURIComponent(origin() + "/login"), origin()), { headers: request.headers }));
    const logout = await revokeAll(target.user.sub);
    const response = NextResponse.json({ redirect: oldLogout.headers.get("location") || "/login" }, { headers: { "Cache-Control": "no-store" } });
    for (const cookie of [...oldLogout.headers.getSetCookie(), ...logout.headers.getSetCookie()]) response.headers.append("set-cookie", cookie);
    return response;
  }); } catch (error) { return failure(error); }
}
