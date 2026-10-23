import { backend, failure, HttpError } from "@/lib/server/auth";
export async function GET(request: Request) {
  try {
    const params = new URL(request.url).searchParams;
    const query = new URLSearchParams();
    for (const [key, value] of params) {
      if (!["cursor", "limit"].includes(key)) throw new HttpError(422, "invalid_request", "Tham số không hợp lệ.");
      query.set(key, value);
    }
    return await backend(request, "/v1/workspaces?" + query);
  } catch (error) { return failure(error); }
}
