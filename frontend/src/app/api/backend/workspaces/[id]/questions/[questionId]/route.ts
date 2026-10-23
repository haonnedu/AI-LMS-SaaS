import { failure } from "@/lib/server/auth";
import { get, putLarge, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "questionId"]);
    return await get(request, `/v1/workspaces/${p.id}/questions/${p.questionId}`);
  } catch (error) { return failure(error); }
}
export async function PUT(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "questionId"]);
    return await putLarge(request, `/v1/workspaces/${p.id}/questions/${p.questionId}`);
  } catch (error) { return failure(error); }
}
