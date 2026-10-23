import { failure } from "@/lib/server/auth";
import { putJson, uuidParams } from "@/lib/server/bff";
export async function PUT(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["attemptId","itemId"]);
    return await putJson(request, `/v1/student/attempts/${p.attemptId}/answers/${p.itemId}`);
  } catch (error) { return failure(error); }
}
