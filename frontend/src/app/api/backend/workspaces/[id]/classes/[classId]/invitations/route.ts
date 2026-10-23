import { failure } from "@/lib/server/auth";
import { postJson, uuidParams } from "@/lib/server/bff";
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "classId"]);
    return await postJson(request, `/v1/workspaces/${p.id}/classes/${p.classId}/invitations`);
  } catch (error) { return failure(error); }
}
