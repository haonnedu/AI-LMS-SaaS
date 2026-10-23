import { betterEnabled } from "@/lib/server/better-auth";
import { NextResponse } from "next/server";
import { auth, failure, lockedSession, HttpError } from "@/lib/server/auth";
export const dynamic = "force-dynamic";
export async function GET() {
  try {
    return await lockedSession(async session => {
      if (!betterEnabled()) await auth().updateSession((await auth().getSession())!);
      return NextResponse.json({ authenticated: true, user: { name: session.user.name || session.user.email, email: session.user.email }, emailVerified: session.user.email_verified === true, csrfToken: session.csrf }, { headers: { "Cache-Control": "no-store" } });
    }, false);
  } catch (error) {
    if (error instanceof HttpError && error.status === 401) return NextResponse.json({ authenticated: false }, { headers: { "Cache-Control": "no-store" } });
    return failure(error);
  }
}
