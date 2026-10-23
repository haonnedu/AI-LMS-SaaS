import { failure } from "@/lib/server/auth";
import { get, postLarge, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "itemId"]);
    return await get(request, `/v1/workspaces/${p.id}/content-items/${p.itemId}/revisions`);
  } catch (error) { return failure(error); }
}
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "itemId"]);
    return await postLarge(request, `/v1/workspaces/${p.id}/content-items/${p.itemId}/revisions`);
  } catch (error) { return failure(error); }
}
