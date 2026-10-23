import { backend, failure } from "@/lib/server/auth";
export async function POST(request: Request) {
  try { return await backend(request, "/v1/auth/bootstrap", "POST"); } catch (error) { return failure(error); }
}
