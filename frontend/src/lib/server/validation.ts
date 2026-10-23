// Pure, dependency-free helpers shared by BFF routes and node:test unit tests.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const INVITE_TOKEN = /^[A-Za-z0-9_-]{32,128}$/;
export const isUuid = (value: unknown): value is string => typeof value === "string" && UUID.test(value);
export const isInviteToken = (value: unknown): value is string => typeof value === "string" && INVITE_TOKEN.test(value);

/** Headers a browser may influence on a raw upload. Everything else is dropped. */
export const UPLOAD_HEADER_ALLOWLIST = ["content-type", "content-length", "x-file-name", "x-rights-attested", "idempotency-key"] as const;
export function pickUploadHeaders(source: Headers): Record<string, string> {
  const picked: Record<string, string> = {};
  for (const name of UPLOAD_HEADER_ALLOWLIST) {
    const value = source.get(name);
    if (value !== null && value.length <= 1024 && !/[\r\n]/.test(value)) picked[name] = value;
  }
  return picked;
}

/** Returns the allowlisted query, or null when any key is unknown or a value is oversized/empty. */
export function allowQuery(params: URLSearchParams, allowed: readonly string[], rules: Record<string, RegExp> = {}): URLSearchParams | null {
  const query = new URLSearchParams();
  for (const [key, value] of params) {
    if (!allowed.includes(key) || query.has(key) || value.length === 0 || value.length > 512) return null;
    if (rules[key] && !rules[key].test(value)) return null;
    query.set(key, value);
  }
  return query;
}
export const QUERY_RULES = { limit: /^\d{1,3}$/, status: /^[a-z_]{1,20}$/, subject: /^[A-Za-z0-9_.-]{1,64}$/, grade: /^\d{1,2}$/, programYear: /^[A-Za-z0-9_-]{1,16}$/ } as const;

/** Accept only same-site relative /join/<token> destinations (no open redirect). */
export function safeJoinReturnTo(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const match = /^\/join\/([A-Za-z0-9_-]{32,128})$/.exec(value);
  return match ? value : null;
}
