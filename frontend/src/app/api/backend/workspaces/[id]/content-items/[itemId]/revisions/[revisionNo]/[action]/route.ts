import { failure } from "@/lib/server/auth";
import { actionParam, intParam, post, uuidParams } from "@/lib/server/bff";
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "itemId"]);
    const no = await intParam(context.params, "revisionNo");
    const action = await actionParam(context.params, "action", ["submit", "approve", "publish"]);
    return await post(request, `/v1/workspaces/${p.id}/content-items/${p.itemId}/revisions/${no}/${action}`);
  } catch (error) { return failure(error); }
}
