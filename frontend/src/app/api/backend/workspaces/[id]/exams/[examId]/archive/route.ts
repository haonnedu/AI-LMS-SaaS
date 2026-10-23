import { failure } from "@/lib/server/auth";
import { post, uuidParams } from "@/lib/server/bff";
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "examId"]);
    return await post(request, `/v1/workspaces/${p.id}/exams/${p.examId}/archive`);
  } catch (error) { return failure(error); }
}
