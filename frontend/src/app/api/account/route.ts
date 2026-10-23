import { NextResponse } from "next/server";
import { betterEnabled } from "@/lib/server/better-auth";
import { backend, failure, lockedSession } from "@/lib/server/auth";
import { methods } from "@/lib/server/account-center";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  if (!betterEnabled()) return new Response(null, { status: 404 });
  try {
    const me = await backend(request, "/v1/me");
    if (!me.ok && me.status !== 409) return me;
    const user = me.ok ? await me.json() : null;
    return await lockedSession(async session => NextResponse.json({ user: { id: user?.id || null, name: session.user.name, email: session.user.email }, methods: (({ password, google }) => ({ password, google }))(await methods(session.user.sub)), googleEnabled: Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET) }, { headers: { "Cache-Control": "no-store" } })); }
  catch (error) { return failure(error); }
}
