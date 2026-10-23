import { NextRequest, NextResponse } from "next/server";
import { appOrigin, auth, checkCsrf, failure, lockedSession } from "@/lib/server/auth";
export async function POST(request: NextRequest) {
  try {
    return await lockedSession(async session => {
      checkCsrf(request, session);
      const internal = new NextRequest(new URL("/auth/logout?returnTo=" + encodeURIComponent(appOrigin() + "/login"), appOrigin()), { headers: request.headers });
      const loggedOut = await auth().middleware(internal);
      const response = NextResponse.json({ redirect: loggedOut.headers.get("location") || "/login" }, { headers: { "Cache-Control": "no-store" } });
      for (const cookie of loggedOut.cookies.getAll()) response.cookies.set(cookie);
      return response;
    }, false);
  } catch (error) { return failure(error); }
}
