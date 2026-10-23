import { betterEnabled } from "@/lib/server/better-auth";
import { NextRequest, NextResponse } from "next/server";
import { auth, failure } from "@/lib/server/auth";

export async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;
  if (betterEnabled() && process.env.AUTH0_MIGRATION_ENABLED !== "1") return new NextResponse(null, { status: 404 });
  // Only SDK login/callback are public. Logout requires our CSRF-protected POST.
  if (!["/auth/login", "/auth/callback"].includes(path)) return new NextResponse(null, { status: 404 });
  try {
    if (path === "/auth/login") {
      const signup = request.nextUrl.searchParams.get("screen_hint") === "signup";
      return await auth().startInteractiveLogin({ returnTo: "/onboarding", authorizationParameters: { ...(signup ? { screen_hint: "signup" } : {}), prompt: "login", max_age: 0 } }, request);
    }
    return await auth().middleware(request);
  } catch (error) { return failure(error); }
}
export const config = { matcher: ["/auth/:path*"] };
