import { failure } from "@/lib/server/auth";
import { actionParam, intParam, post, uuidParams } from "@/lib/server/bff";
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "blueprintId"]);
    const no = await intParam(context.params, "versionNo");
    const action = await actionParam(context.params, "action", ["validate", "publish"]);
    return await post(request, `/v1/workspaces/${p.id}/blueprints/${p.blueprintId}/versions/${no}/${action}`);
  } catch (error) { return failure(error); }
}
