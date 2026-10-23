import { failure } from "@/lib/server/auth";
import { get, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "requestId"]);
    return await get(request, `/v1/workspaces/${p.id}/privacy-requests/${p.requestId}`);
  } catch (error) { return failure(error); }
}
