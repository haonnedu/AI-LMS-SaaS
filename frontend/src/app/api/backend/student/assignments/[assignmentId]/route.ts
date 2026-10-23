import { failure } from "@/lib/server/auth";
import { get, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["assignmentId"]);
    return await get(request, `/v1/student/assignments/${p.assignmentId}`);
  } catch (error) { return failure(error); }
}
