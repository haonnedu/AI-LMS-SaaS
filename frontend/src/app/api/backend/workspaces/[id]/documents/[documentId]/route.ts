import { failure } from "@/lib/server/auth";
import { del, get, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "documentId"]);
    return await get(request, `/v1/workspaces/${p.id}/documents/${p.documentId}`);
  } catch (error) { return failure(error); }
}
export async function DELETE(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id", "documentId"]);
    return await del(request, `/v1/workspaces/${p.id}/documents/${p.documentId}`);
  } catch (error) { return failure(error); }
}
