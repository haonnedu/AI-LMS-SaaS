import { failure } from "@/lib/server/auth";
import { get, queryString, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id"]);
    return await get(request, `/v1/workspaces/${p.id}/jobs` + queryString(request, ["cursor","limit","status"]));
  } catch (error) { return failure(error); }
}
