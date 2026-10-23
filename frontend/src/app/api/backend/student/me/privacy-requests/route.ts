import { failure } from "@/lib/server/auth";
import { postJson } from "@/lib/server/bff";
export async function POST(request: Request) {
  try { return await postJson(request, "/v1/student/me/privacy-requests"); }
  catch (error) { return failure(error); }
}
