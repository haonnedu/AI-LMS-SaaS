export class RequestError extends Error {
  constructor(public status: number, public code: string, message: string, public detail?: Record<string, unknown>) { super(message); }
}
export type Session = { authenticated: boolean; emailVerified?: boolean; csrfToken?: string; user?: { name: string; email: string } };
/** Same-origin JSON request. Throws RequestError for non-2xx; 204 resolves to null. */
export async function read(url: string, init?: RequestInit, timeoutMs = 15000) {
  const response = await fetch(url, { ...init, cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
  if (response.status === 204) return null;
  let payload;
  try { payload = await response.json(); }
  catch { throw new RequestError(response.status, "request_failed", "Chưa thể hoàn thành. Vui lòng thử lại."); }
  if (!response.ok) {
    throw new RequestError(response.status, payload.error?.code || "request_failed", payload.error?.message || "Chưa thể hoàn thành. Vui lòng thử lại.", payload.error);
  }
  return payload;
}
export function jsonInit(csrfToken: string, body?: unknown): RequestInit {
  return { method: "POST", headers: { "X-CSRF-Token": csrfToken, ...(body === undefined ? {} : { "Content-Type": "application/json" }) }, body: body === undefined ? undefined : JSON.stringify(body) };
}
