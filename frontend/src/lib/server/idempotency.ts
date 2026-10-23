import { randomUUID } from "node:crypto";
import { HttpError, backend } from "./auth";
import { isIdempotencyKey } from "./validation";

/** Client-supplied Idempotency-Key when well formed (so retries reuse it), else a fresh UUID. A malformed key is rejected, never forwarded. */
export function idempotencyKey(request: Request): string {
  const supplied = request.headers.get("idempotency-key");
  if (supplied === null || supplied === "") return randomUUID();
  if (!isIdempotencyKey(supplied)) throw new HttpError(422, "invalid_request", "Khóa idempotency không hợp lệ.");
  return supplied;
}
/** POST with no body that forwards only the Idempotency-Key header. */
export const postIdempotent = (request: Request, path: string) => backend(request, path, "POST", { headers: { "Idempotency-Key": idempotencyKey(request) } });
