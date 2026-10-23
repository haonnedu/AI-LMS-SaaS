import { failure } from "@/lib/server/auth";
import { get } from "@/lib/server/bff";
export async function GET(request: Request) {
  try { return await get(request, "/v1/student/me/consent-status"); }
  catch (error) { return failure(error); }
}
