import { failure } from "@/lib/server/auth";
import { get, postLarge, queryString, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id"]);
    return await get(request, `/v1/workspaces/${p.id}/content-items` + queryString(request, ["kind", "status", "cursor", "limit"]));
  } catch (error) { return failure(error); }
}
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id"]);
    return await postLarge(request, `/v1/workspaces/${p.id}/content-items`);
  } catch (error) { return failure(error); }
}
