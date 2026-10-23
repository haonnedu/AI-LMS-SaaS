import { failure } from "@/lib/server/auth";
import { get, postJson, queryString, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id"]);
    return await get(request, `/v1/workspaces/${p.id}/classes` + queryString(request, ["cursor","limit","status"]));
  } catch (error) { return failure(error); }
}
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id"]);
    return await postJson(request, `/v1/workspaces/${p.id}/classes`);
  } catch (error) { return failure(error); }
}
