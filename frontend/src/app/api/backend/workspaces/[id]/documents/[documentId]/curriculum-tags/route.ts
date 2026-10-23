import { backend, failure } from "@/lib/server/auth";
import { get, jsonBody, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id","documentId"]);
    return await get(request, `/v1/workspaces/${p.id}/documents/${p.documentId}/curriculum-tags`);
  } catch (error) { return failure(error); }
}
export async function PUT(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id","documentId"]);
    return await backend(request, `/v1/workspaces/${p.id}/documents/${p.documentId}/curriculum-tags`, "PUT", await jsonBody(request));
  } catch (error) { return failure(error); }
}
