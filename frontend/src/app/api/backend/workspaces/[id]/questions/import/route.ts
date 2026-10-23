import { failure } from "@/lib/server/auth";
import { csvImport, uuidParams } from "@/lib/server/bff";
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id"]);
    return await csvImport(request, `/v1/workspaces/${p.id}/questions/import`);
  } catch (error) { return failure(error); }
}
