import { backend, failure, HttpError } from "@/lib/server/auth";
export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await context.params;
    if (!/^[0-9a-f-]{36}$/i.test(id)) throw new HttpError(422, "invalid_request", "Workspace không hợp lệ.");
    return await backend(request, "/v1/workspaces/" + id);
  } catch (error) { return failure(error); }
}
