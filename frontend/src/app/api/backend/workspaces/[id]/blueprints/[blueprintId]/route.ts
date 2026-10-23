import { failure } from "@/lib/server/auth";
import { get, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "blueprintId"]);
    return await get(request, `/v1/workspaces/${p.id}/blueprints/${p.blueprintId}`);
  } catch (error) { return failure(error); }
}
