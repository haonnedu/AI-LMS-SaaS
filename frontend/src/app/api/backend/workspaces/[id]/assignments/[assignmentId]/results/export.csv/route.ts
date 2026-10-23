import { failure } from "@/lib/server/auth";
import { getCsv, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id","assignmentId"]);
    return await getCsv(request, `/v1/workspaces/${p.id}/assignments/${p.assignmentId}/results/export.csv`);
  } catch (error) { return failure(error); }
}
