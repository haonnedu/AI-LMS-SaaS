import { failure } from "@/lib/server/auth";
import { putLarge, uuidParams } from "@/lib/server/bff";
export async function PUT(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "itemId"]);
    return await putLarge(request, `/v1/workspaces/${p.id}/content-items/${p.itemId}/draft`);
  } catch (error) { return failure(error); }
}
