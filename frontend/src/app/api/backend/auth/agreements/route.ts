import { createHash } from "node:crypto";
import { sanitizeAcceptance } from "@/lib/client/agreements";
import { backend, failure, HttpError } from "@/lib/server/auth";
import { jsonBody } from "@/lib/server/bff";

export async function GET(request: Request) {
  try { return await backend(request, "/v1/auth/agreements"); } catch (error) { return failure(error); }
}

/** Records acceptance of the user agreement + privacy notice. Only a sha256 of the browser user agent is forwarded, never the IP. */
export async function POST(request: Request) {
  try {
    const { body, headers } = await jsonBody(request);
    const accepted = sanitizeAcceptance(JSON.parse(body));
    if (!accepted) throw new HttpError(422, "invalid_request", "Nội dung không hợp lệ.");
    const agent = request.headers.get("user-agent");
    const clientHash = agent ? createHash("sha256").update(agent.slice(0, 1024)).digest("hex") : undefined;
    return await backend(request, "/v1/auth/agreements", "POST", { body: JSON.stringify({ ...accepted, ...(clientHash ? { clientHash } : {}) }), headers });
  } catch (error) { return failure(error); }
}
