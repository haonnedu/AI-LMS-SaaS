import { failure } from "@/lib/server/auth";
import { putJson } from "@/lib/server/bff";
export async function PUT(request: Request) {
  try { return await putJson(request, "/v1/student/me/birth-year"); }
  catch (error) { return failure(error); }
}
