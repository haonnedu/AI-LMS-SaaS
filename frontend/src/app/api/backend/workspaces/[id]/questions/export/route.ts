import { failure, HttpError } from "@/lib/server/auth";
import { getCsv, queryString, uuidParams } from "@/lib/server/bff";
export async function GET(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const p = await uuidParams(context.params, ["id"]);
    const query = queryString(request, ["audience"]);
    if (!query) throw new HttpError(422, "invalid_request", "Thiếu loại tệp xuất.");
    return await getCsv(request, `/v1/workspaces/${p.id}/questions/export` + query);
  } catch (error) { return failure(error); }
}
