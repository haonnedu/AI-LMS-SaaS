import { failure } from "@/lib/server/auth";
import { uuidParams } from "@/lib/server/bff";
import { postIdempotent } from "@/lib/server/idempotency";
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["assignmentId"]);
    return await postIdempotent(request, `/v1/student/assignments/${p.assignmentId}/attempts`);
  } catch (error) { return failure(error); }
}
