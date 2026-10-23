import { failure } from "@/lib/server/auth";
import { get, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id","documentId"]);
    return await get(request, `/v1/workspaces/${p.id}/documents/${p.documentId}/embedding-runs`);
  } catch (error) { return failure(error); }
}
