import { NextResponse } from "next/server";
import { callConsentLink, CONSENT_LINK_BODY_MAX } from "@/lib/server/consent-link";

export const dynamic = "force-dynamic";
const HEADERS = { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" };
const reply = (status: number, payload: unknown) => NextResponse.json(payload, { status, headers: HEADERS });
const problem = (status: number, code: string, message: string) => reply(status, { error: { code, message } });
const TOKEN = /^[A-Za-z0-9_-]{32,128}$/;

export async function GET(_request: Request, context: { params: Promise<{ token: string }> }) {
  const { token } = await context.params;
  if (!TOKEN.test(token)) return problem(404, "not_found", "Liên kết không hợp lệ.");
  const result = await callConsentLink(token, "GET");
  return reply(result.status, result.payload);
}

export async function POST(request: Request, context: { params: Promise<{ token: string }> }) {
  const site = request.headers.get("sec-fetch-site");
  if (site !== "same-origin" && site !== "none") return problem(403, "forbidden", "Yêu cầu không hợp lệ.");
  const { token } = await context.params;
  if (!TOKEN.test(token)) return problem(404, "not_found", "Liên kết không hợp lệ.");
  if (!(request.headers.get("content-type") || "").toLowerCase().startsWith("application/json")) return problem(415, "unsupported_media_type", "Định dạng yêu cầu không hợp lệ.");
  const text = await request.text();
  if (Buffer.byteLength(text) > CONSENT_LINK_BODY_MAX) return problem(413, "request_too_large", "Yêu cầu quá lớn.");
  let value: unknown;
  try { value = JSON.parse(text); } catch { return problem(422, "invalid_request", "Nội dung không hợp lệ."); }
  if (typeof value !== "object" || value === null || Array.isArray(value)) return problem(422, "invalid_request", "Nội dung không hợp lệ.");
  const result = await callConsentLink(token, "POST", JSON.stringify(value));
  return reply(result.status, result.payload);
}
