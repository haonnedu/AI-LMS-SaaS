import { better } from "@/lib/server/better-auth";
import { NextRequest, NextResponse } from "next/server";
import { checkCsrf, failure, lockedSession } from "@/lib/server/auth";
export async function POST(request: NextRequest) {
  try {
    return await lockedSession(async session => {
      checkCsrf(request, session);
      const result = await better().api.signOut({ headers: request.headers, asResponse: true });
      const response = NextResponse.json({ redirect: "/login" }, { headers: { "Cache-Control": "no-store" } });
      for (const cookie of result.headers.getSetCookie()) response.headers.append("set-cookie", cookie);
      return response;
    }, false);
  } catch (error) { return failure(error); }
}
