import { failure } from "@/lib/server/auth";
import { postLarge, uuidParams } from "@/lib/server/bff";
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id"]);
    return await postLarge(request, `/v1/workspaces/${p.id}/generation/drafts`);
  } catch (error) { return failure(error); }
}
