import { failure } from "@/lib/server/auth";
import { get, queryString, upload, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id"]);
    return await get(request, `/v1/workspaces/${p.id}/documents` + queryString(request, ["cursor","limit"]));
  } catch (error) { return failure(error); }
}
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id"]);
    return await upload(request, `/v1/workspaces/${p.id}/documents`);
  } catch (error) { return failure(error); }
}
export const maxDuration = 120;
