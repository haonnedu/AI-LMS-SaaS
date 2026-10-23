import { failure } from "@/lib/server/auth";
import { postJson, uuidParams } from "@/lib/server/bff";
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id","assignmentId","attemptId"]);
    return await postJson(request, `/v1/workspaces/${p.id}/assignments/${p.assignmentId}/attempts/${p.attemptId}/override`);
  } catch (error) { return failure(error); }
}
