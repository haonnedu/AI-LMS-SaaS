import { failure } from "@/lib/server/auth";
import { get, intParam, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "itemId"]);
    const no = await intParam(context.params, "revisionNo");
    return await get(request, `/v1/workspaces/${p.id}/content-items/${p.itemId}/revisions/${no}/provenance`);
  } catch (error) { return failure(error); }
}
