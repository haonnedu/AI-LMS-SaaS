import { backend, failure } from "@/lib/server/auth";
export async function GET(request: Request) {
  try { return await backend(request, "/v1/me"); } catch (error) { return failure(error); }
}
