import { failure } from "@/lib/server/auth";
import { get, postLarge, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id","classId"]);
    return await get(request, `/v1/workspaces/${p.id}/classes/${p.classId}/assignments`);
  } catch (error) { return failure(error); }
}
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id","classId"]);
    return await postLarge(request, `/v1/workspaces/${p.id}/classes/${p.classId}/assignments`);
  } catch (error) { return failure(error); }
}
