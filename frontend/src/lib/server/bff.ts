import { NextResponse } from "next/server";
import { accessToken, backend, backendOrigin, HttpError, lockedSession } from "./auth";
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

/** Positive integer route param (revision / version numbers). */
export async function intParam(params: Params, name: string) {
  const value = (await params)[name];
  if (typeof value !== "string" || !/^[1-9]\d{0,5}$/.test(value)) throw invalid("Số thứ tự");
  return value;
}
/** One of an allowlisted set of path actions (e.g. submit/approve/publish). */
export async function actionParam(params: Params, name: string, allowed: readonly string[]) {
  const value = (await params)[name];
  if (typeof value !== "string" || !allowed.includes(value)) throw invalid("Thao tác");
  return value;
}
export const AUTHORING_JSON_MAX = 262144;
/** Like jsonBody but with the larger limit needed for authored content bodies. Body text is never logged. */
export async function largeJsonBody(request: Request, max = AUTHORING_JSON_MAX) {
  if (!(request.headers.get("content-type") || "").toLowerCase().startsWith("application/json")) throw new HttpError(415, "unsupported_media_type", "Định dạng yêu cầu không hợp lệ.");
  const text = await request.text();
  if (text.length > max) throw new HttpError(413, "request_too_large", "Yêu cầu quá lớn.");
  let value: unknown;
  try { value = JSON.parse(text); } catch { throw invalid("Nội dung"); }
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw invalid("Nội dung");
  return { body: JSON.stringify(value), headers: { "Content-Type": "application/json" } };
}
export const postLarge = async (request: Request, path: string) => backend(request, path, "POST", await largeJsonBody(request));
export const putLarge = async (request: Request, path: string) => backend(request, path, "PUT", await largeJsonBody(request));
export const putJson = async (request: Request, path: string) => backend(request, path, "PUT", await jsonBody(request));
export const CSV_IMPORT_MAX = 2097152;
/** Raw text/csv import: only content-type is forwarded; body is size-capped. */
export async function csvImport(request: Request, path: string) {
  const type = (request.headers.get("content-type") || "").toLowerCase();
  if (!type.startsWith("text/csv")) throw new HttpError(415, "unsupported_media_type", "Định dạng yêu cầu không hợp lệ.");
  const text = await request.text();
  if (text.length > CSV_IMPORT_MAX) throw new HttpError(413, "request_too_large", "Tệp quá lớn (tối đa 2 MB).");
  return backend(request, path, "POST", { body: text, headers: { "content-type": "text/csv; charset=utf-8" }, passthroughStatus: true });
}
/** GET that relays a text/csv upstream body (backend() only supports JSON). Reuses auth.ts session + token handling. */
export async function getCsv(request: Request, path: string) {
  void request;
  const token = await lockedSession(() => accessToken());
  const base = backendOrigin();
  const response = await fetch(new URL(path, base), { method: "GET", headers: { Authorization: `Bearer ${token}`, Accept: "text/csv, application/json" }, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(30000) });
  const type = response.headers.get("content-type") || "";
  if (response.ok && type.toLowerCase().startsWith("text/csv")) {
    return new NextResponse(response.body, { status: 200, headers: { "Content-Type": "text/csv; charset=utf-8", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
  }
  let payload: unknown;
  try { payload = await response.json(); } catch { throw new HttpError(503, "upstream_error", "Dịch vụ tạm thời không khả dụng. Vui lòng thử lại."); }
  return NextResponse.json(payload, { status: response.ok ? 502 : response.status, headers: { "Cache-Control": "no-store" } });
}
