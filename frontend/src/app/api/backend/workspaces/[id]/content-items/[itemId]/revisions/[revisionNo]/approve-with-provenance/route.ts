import { failure } from "@/lib/server/auth";
import { intParam, post, uuidParams } from "@/lib/server/bff";
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "itemId"]);
    const no = await intParam(context.params, "revisionNo");
    return await post(request, `/v1/workspaces/${p.id}/content-items/${p.itemId}/revisions/${no}/approve-with-provenance`);
  } catch (error) { return failure(error); }
}
