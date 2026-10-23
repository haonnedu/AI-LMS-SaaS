// Pure, dependency-free privacy/consent helpers (node:test friendly). Never log birth years, guardian data or tokens.
import type { ConsentStatus, StudentConsentItem } from "./privacy-types";

/** Default age below which guardian consent is needed (Nghị định 13/2023/NĐ-CP: dưới 16 tuổi). Configurable per call. */
export const DEFAULT_CONSENT_AGE = 16;
export const MIN_BIRTH_YEAR = 1990;

export const ageFromBirthYear = (birthYear: number, now: Date = new Date()): number => now.getFullYear() - birthYear;
export function isMinor(birthYear: number | null | undefined, threshold = DEFAULT_CONSENT_AGE, now: Date = new Date()): boolean {
  if (typeof birthYear !== "number" || !Number.isInteger(birthYear)) return false;
  return ageFromBirthYear(birthYear, now) < threshold;
}
export function isValidBirthYear(value: unknown, now: Date = new Date()): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= MIN_BIRTH_YEAR && value <= now.getFullYear();
}
/** Descending list from the current year to MIN_BIRTH_YEAR for a select. */
export function birthYearOptions(now: Date = new Date(), min = MIN_BIRTH_YEAR): number[] {
  const out: number[] = [];
  for (let year = now.getFullYear(); year >= min; year--) out.push(year);
  return out;
}

export const CONSENT_LABEL: Record<ConsentStatus, string> = { unknown: "Chưa rõ", not_required: "Không cần", pending: "Đang chờ", granted: "Đã đồng ý", revoked: "Đã thu hồi" };
export const CONSENT_TONE: Record<ConsentStatus, string | undefined> = { unknown: "info", not_required: undefined, pending: "warn", granted: undefined, revoked: "error" };
export const consentLabel = (status: string): string => (CONSENT_LABEL as Record<string, string>)[status] ?? "Không rõ";
export const consentTone = (status: string): string | undefined => (CONSENT_TONE as Record<string, string | undefined>)[status];

export const CONSENT_METHOD_LABEL: Record<string, string> = { paper_school: "Giấy tại trường", self_adult: "Học sinh đủ tuổi tự đồng ý" };
export const consentMethodLabel = (method: string): string => CONSENT_METHOD_LABEL[method] ?? method;

/** One-time guardian link shown to the teacher. */
export const consentLinkUrl = (origin: string, token: string): string => `${origin.replace(/\/+$/, "")}/consent/${token}`;

/** Vietnamese given name is the last word of the full name. Public consent pages show only this. */
export function givenName(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : "";
}

export const needsBirthYear = (items: readonly StudentConsentItem[]): boolean => items.some(item => item.consentStatus === "unknown");
/** Birth year and the parent-consent card are only part of the optional "guardian" mode (decision 0009). */
export const guardianFlowEnabled = (mode: unknown): boolean => mode === "guardian";
/** After a server-side consent_required refusal, the card is hidden only when the server says it runs in "signup" mode. */
export const showsGuardianCard = (mode: unknown): boolean => mode !== "signup";
export const blockingConsents = (items: readonly StudentConsentItem[]): StudentConsentItem[] => items.filter(item => item.consentRequired && item.consentStatus !== "granted");

export const CONSENT_REQUIRED_MESSAGE = "Cần sự đồng ý của phụ huynh trước khi em làm bài. Thầy cô hoặc nhà trường sẽ ghi nhận việc này.";

/** The active (granted, not revoked) consent a teacher may revoke. */
export function activeConsentId(consents: readonly { id: string; grantedAt: string | null; revokedAt: string | null }[]): string | null {
  for (const consent of consents) if (consent.grantedAt && !consent.revokedAt) return consent.id;
  return null;
}
export function latestPolicyVersion(items: readonly { consents: readonly { policyVersion: string }[] }[]): string | null {
  for (const item of items) if (item.consents.length) return item.consents[0].policyVersion;
  return null;
}

// --- Privacy request polling (pure) ---
const TERMINAL = new Set(["completed", "succeeded", "ready", "done", "failed", "cancelled", "rejected", "expired"]);
const FAILED = new Set(["failed", "cancelled", "rejected", "expired"]);
export const REQUEST_POLL_BASE_MS = 2000;
export const REQUEST_POLL_MAX_MS = 15000;
export const REQUEST_POLL_MAX_ATTEMPTS = 60;
export const isRequestTerminal = (status: string): boolean => TERMINAL.has(status);
export const isRequestFailed = (status: string): boolean => FAILED.has(status);
/** Delay before next poll: gentle growth with attempts, backoff on consecutive errors, capped. */
export function requestPollDelay(attempt: number, consecutiveErrors = 0): number {
  const growth = REQUEST_POLL_BASE_MS * (1 + Math.floor(Math.max(0, attempt) / 5));
  return Math.min(REQUEST_POLL_MAX_MS, growth * 2 ** Math.min(Math.max(0, consecutiveErrors), 3));
}
export type RequestPollView = { status: string; downloadUrl?: string | null };
/** Keep polling until terminal, a download link exists, or the attempt budget is spent. */
export function shouldPollRequest(request: RequestPollView | null, attempt: number): boolean {
  if (!request) return false;
  if (request.downloadUrl) return false;
  if (isRequestTerminal(request.status)) return false;
  return attempt < REQUEST_POLL_MAX_ATTEMPTS;
}
/** Only http(s) or same-origin absolute paths may be rendered as download links. */
export function safeDownloadUrl(value: string | null | undefined): string | null {
  if (typeof value !== "string" || !value || /[\s<>"']/.test(value)) return null;
  if (/^https?:\/\//i.test(value) || (value.startsWith("/") && !value.startsWith("//"))) return value;
  return null;
}
export function requestStatusText(kind: "export" | "erasure", status: string): string {
  if (isRequestFailed(status)) return "Yêu cầu chưa thực hiện được. Vui lòng thử lại sau.";
  if (isRequestTerminal(status)) return kind === "export" ? "Bản sao dữ liệu đã sẵn sàng." : "Yêu cầu xóa đã hoàn tất.";
  return kind === "export" ? "Đang chuẩn bị bản sao dữ liệu…" : "Đang xử lý yêu cầu xóa…";
}

// --- Public consent link outcomes ---
export type ConsentLinkOutcome = "ok" | "invalid" | "expired" | "used" | "rate_limited" | "error";
export function consentLinkOutcome(status: number, code?: string): ConsentLinkOutcome {
  if (status >= 200 && status < 300) return "ok";
  if (status === 429) return "rate_limited";
  if (status === 404) return "invalid";
  if (status === 409 || (status === 410 && /used|consumed|granted/i.test(code ?? ""))) return "used";
  if (status === 410) return "expired";
  return "error";
}
export const isConsentToken = (value: unknown): value is string => typeof value === "string" && /^[A-Za-z0-9_-]{32,128}$/.test(value);
