import { failure } from "@/lib/server/auth";
import { get, queryString, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id","documentId","versionId"]);
    return await get(request, `/v1/workspaces/${p.id}/documents/${p.documentId}/versions/${p.versionId}/chunks` + queryString(request, ["cursor", "limit"]));
  } catch (error) { return failure(error); }
}
