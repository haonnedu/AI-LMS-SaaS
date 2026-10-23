import { failure } from "@/lib/server/auth";
import { get, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "exportId"]);
    return await get(request, `/v1/workspaces/${p.id}/exports/${p.exportId}`);
  } catch (error) { return failure(error); }
}
