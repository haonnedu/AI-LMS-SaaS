import { failure } from "@/lib/server/auth";
import { post, tokenParam } from "@/lib/server/bff";
export async function POST(request: Request, context: { params: Promise<Record<string, string>> }) {
  try {
    const token = await tokenParam(context.params);
    return await post(request, `/v1/invitations/${token}/accept`);
  } catch (error) { return failure(error); }
}
