import { failure } from "@/lib/server/auth";
import { intParam, post, uuidParams } from "@/lib/server/bff";
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "examId"]);
    const no = await intParam(context.params, "versionNo");
    return await post(request, `/v1/workspaces/${p.id}/exams/${p.examId}/versions/${no}/publish`);
  } catch (error) { return failure(error); }
}
