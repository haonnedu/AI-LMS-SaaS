import { failure } from "@/lib/server/auth";
import { actionParam, post, uuidParams } from "@/lib/server/bff";
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "assignmentId"]);
    const action = await actionParam(context.params, "action", ["publish", "close", "archive", "release-scores", "release-solutions"]);
    return await post(request, `/v1/workspaces/${p.id}/assignments/${p.assignmentId}/${action}`);
  } catch (error) { return failure(error); }
}
