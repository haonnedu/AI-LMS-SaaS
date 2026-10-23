import { failure } from "@/lib/server/auth";
import { putJson, uuidParams } from "@/lib/server/bff";
export async function PUT(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "questionId"]);
    return await putJson(request, `/v1/workspaces/${p.id}/questions/${p.questionId}/key`);
  } catch (error) { return failure(error); }
}
