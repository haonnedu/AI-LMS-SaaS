import { backendOrigin } from "./auth";

export const CONSENT_LINK_BODY_MAX = 4096;
export type UpstreamResult = { status: number; payload: unknown };
const unavailable = { error: { code: "service_unavailable", message: "Dịch vụ tạm thời không khả dụng. Vui lòng thử lại." } };

/**
 * Calls the public consent-link API directly (no session, no cookies, no caller headers forwarded).
 * Tokens and bodies are never logged. 5xx is collapsed to a generic 503.
 */
export async function callConsentLink(token: string, method: "GET" | "POST", body?: string): Promise<UpstreamResult> {
  try {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const response = await fetch(new URL(`/v1/public/consent-links/${token}`, backendOrigin()), { method, headers, body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(8000) });
    let payload: unknown = null;
    try { payload = await response.json(); } catch { payload = null; }
    if (response.status >= 500 || (payload === null && response.status !== 204)) return { status: response.status >= 500 ? 503 : 502, payload: unavailable };
    return { status: response.status, payload };
  } catch {
    return { status: 503, payload: unavailable };
  }
}
export const errorCode = (payload: unknown): string | undefined => {
  const error = (payload as { error?: { code?: unknown } } | null)?.error;
  return typeof error?.code === "string" ? error.code : undefined;
};
