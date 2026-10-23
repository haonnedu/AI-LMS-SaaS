import { failure } from "@/lib/server/auth";
import { get, intParam, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "examId"]);
    const no = await intParam(context.params, "versionNo");
    return await get(request, `/v1/workspaces/${p.id}/exams/${p.examId}/versions/${no}/student-view`);
  } catch (error) { return failure(error); }
}
