import { backend, HttpError } from "./auth";
import { allowQuery, isInviteToken, isUuid, pickUploadHeaders, QUERY_RULES } from "./validation";

export type Params = Promise<Record<string, string>>;
const invalid = (label: string) => new HttpError(422, "invalid_request", `${label} không hợp lệ.`);
/** Validates named route params as UUIDs; returns them untouched only when valid. */
export async function uuidParams(params: Params, names: string[]) {
  const values = await params;
  const out: Record<string, string> = {};
  for (const name of names) {
    const value = values[name];
    if (!isUuid(value)) throw invalid("Mã định danh");
    out[name] = value.toLowerCase();
  }
  return out;
}
export async function tokenParam(params: Params) {
  const { token } = await params;
  if (!isInviteToken(token)) throw invalid("Mã mời");
  return token;
}
export function queryString(request: Request, allowed: readonly string[]) {
  const query = allowQuery(new URL(request.url).searchParams, allowed, QUERY_RULES);
  if (!query) throw invalid("Tham số");
  const text = query.toString();
  return text ? "?" + text : "";
}
/** Forward a JSON body parsed and re-serialised, so only well-formed JSON objects reach the API. */
export async function jsonBody(request: Request) {
  if (!(request.headers.get("content-type") || "").toLowerCase().startsWith("application/json")) throw new HttpError(415, "unsupported_media_type", "Định dạng yêu cầu không hợp lệ.");
  const text = await request.text();
  if (text.length > 4096) throw new HttpError(413, "request_too_large", "Yêu cầu quá lớn.");
  let value: unknown;
  try { value = JSON.parse(text); } catch { throw invalid("Nội dung"); }
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw invalid("Nội dung");
  return { body: JSON.stringify(value), headers: { "Content-Type": "application/json" } };
}
export const get = (request: Request, path: string) => backend(request, path);
export const post = (request: Request, path: string) => backend(request, path, "POST");
export const postJson = async (request: Request, path: string) => backend(request, path, "POST", await jsonBody(request));
export const del = (request: Request, path: string) => backend(request, path, "DELETE");
export const upload = (request: Request, path: string) => backend(request, path, "POST", { body: request.body, headers: pickUploadHeaders(request.headers), passthroughStatus: true });
