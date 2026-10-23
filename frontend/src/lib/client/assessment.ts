// Pure helpers for assignments, the student quiz and results. No DOM, no timers, no path aliases (loaded directly by node:test).

/* ---------- server clock + countdown ---------- */
export const WARNING_MS = 120000;
/** serverNow - deviceNow. Add to Date.now() to estimate server time; refreshed from every API response. */
export function clockOffset(serverNow: string | null | undefined, deviceNow: number = Date.now()): number | null {
  const parsed = serverNow ? Date.parse(serverNow) : NaN;
  return Number.isFinite(parsed) ? parsed - deviceNow : null;
}
export const serverTime = (offsetMs: number, deviceNow: number = Date.now()) => deviceNow + offsetMs;
/** Milliseconds until the instant (server time based), or null when there is none. Never negative. */
export function remainingMs(target: string | null | undefined, offsetMs: number, deviceNow: number = Date.now()): number | null {
  const at = target ? Date.parse(target) : NaN;
  if (!Number.isFinite(at)) return null;
  return Math.max(0, at - serverTime(offsetMs, deviceNow));
}
export function formatCountdown(ms: number): string {
  const total = Math.ceil(Math.max(0, ms) / 1000);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const two = (n: number) => String(n).padStart(2, "0");
  if (days > 0) return `${days} ngày ${hours} giờ`;
  if (hours > 0) return `${hours}:${two(minutes)}:${two(seconds)}`;
  return `${two(minutes)}:${two(seconds)}`;
}
export type TimerPhase = "none" | "running" | "warning" | "expired";
export function timerPhase(ms: number | null): TimerPhase {
  if (ms === null) return "none";
  if (ms <= 0) return "expired";
  return ms <= WARNING_MS ? "warning" : "running";
}
export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return "Không giới hạn";
  const minutes = Math.round(seconds / 60);
  return minutes >= 60 && minutes % 60 === 0 ? `${minutes / 60} giờ` : `${Math.max(1, minutes)} phút`;
}

/* ---------- availability ---------- */
export type Availability = "resume" | "open" | "not_open_yet" | "closed" | "limit_reached" | "done";
export const AVAILABILITY_LABEL: Record<Availability, string> = { resume: "Đang làm dở", open: "Đang mở", not_open_yet: "Chưa mở", closed: "Đã đóng", limit_reached: "Hết lượt làm", done: "Đã hoàn thành" };
export const AVAILABILITY_TONE: Record<Availability, "info" | "warn" | "error" | undefined> = { resume: "info", open: undefined, not_open_yet: "warn", closed: "error", limit_reached: "warn", done: undefined };
export const AVAILABILITY_ORDER: readonly Availability[] = ["resume", "open", "not_open_yet", "done", "limit_reached", "closed"];
export const AVAILABILITY_GROUP: Record<Availability, string> = { resume: "Đang làm dở", open: "Có thể làm bài", not_open_yet: "Sắp mở", done: "Đã hoàn thành", limit_reached: "Hết lượt làm", closed: "Đã đóng" };
export const canStart = (availability: Availability) => availability === "resume" || availability === "open";
export const startLabel = (availability: Availability) => availability === "resume" ? "Tiếp tục" : "Bắt đầu làm bài";
export function groupByAvailability<T extends { availability: Availability }>(items: readonly T[]): { availability: Availability; items: T[] }[] {
  return AVAILABILITY_ORDER.map(availability => ({ availability, items: items.filter(item => item.availability === availability) })).filter(group => group.items.length > 0);
}
/** One-line hint such as "Mở sau 1 ngày 2 giờ" / "Còn 03:20:10" / "Không giới hạn thời gian đóng". */
export function windowHint(opensAt: string, closesAt: string | null, offsetMs: number, deviceNow: number = Date.now()): string {
  const toOpen = remainingMs(opensAt, offsetMs, deviceNow);
  if (toOpen !== null && toOpen > 0) return `Mở sau ${formatCountdown(toOpen)}`;
  if (!closesAt) return "Không giới hạn thời gian đóng";
  const toClose = remainingMs(closesAt, offsetMs, deviceNow);
  return toClose === null || toClose <= 0 ? "Đã quá hạn" : `Đóng sau ${formatCountdown(toClose)}`;
}

/* ---------- idempotency keys kept in sessionStorage ---------- */
export type KeyStorage = { getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem(key: string): void };
const KEY_FORMAT = /^[A-Za-z0-9_-]{8,128}$/;
export function newKey(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  return "k" + Math.random().toString(36).slice(2) + Date.now().toString(36) + Math.random().toString(36).slice(2);
}
const memory = new Map<string, string>();
const storageKey = (scope: string, id: string) => `eduvia.idem.${scope}.${id}`;
/** Existing key for (scope,id) or a freshly stored one; falls back to memory when storage is unavailable. */
export function getIdempotencyKey(storage: KeyStorage | null, scope: string, id: string, generate: () => string = newKey): string {
  const name = storageKey(scope, id);
  try {
    const existing = storage?.getItem(name) ?? memory.get(name) ?? null;
    if (existing && KEY_FORMAT.test(existing)) return existing;
  } catch { const kept = memory.get(name); if (kept) return kept; }
  const created = generate();
  memory.set(name, created);
  try { storage?.setItem(name, created); } catch { /* memory copy still protects retries */ }
  return created;
}
export function clearIdempotencyKey(storage: KeyStorage | null, scope: string, id: string) {
  const name = storageKey(scope, id);
  memory.delete(name);
  try { storage?.removeItem(name); } catch { /* ignore */ }
}

/* ---------- per-item autosave state machine ---------- */
export type ItemStatus = "saved" | "dirty" | "saving" | "error";
export type ItemSave = {
  savedKey: string | null; desiredKey: string | null;
  revision: number; sequence: number; status: ItemStatus; inflight: boolean;
  /** Set when the server value replaced ours after a stale_answer conflict. */
  refreshed: boolean;
};
export type SaveRequest = { selectedKey: string | null; expectedRevision: number; clientSequence: number };
export type ServerItem = { selectedKey: string | null; answerRevision: number; clientSequence: number };
export const initItem = (item: ServerItem): ItemSave => ({ savedKey: item.selectedKey, desiredKey: item.selectedKey, revision: item.answerRevision, sequence: item.clientSequence, status: "saved", inflight: false, refreshed: false });
/** The user chose (or cleared) an answer. Does not send. */
export function selectAnswer(state: ItemSave, key: string | null): ItemSave {
  if (state.desiredKey === key && state.status !== "error") return state;
  const matchesSaved = key === state.savedKey && !state.inflight;
  return { ...state, desiredKey: key, refreshed: false, status: state.inflight ? "saving" : matchesSaved ? "saved" : "dirty" };
}
export const needsSave = (state: ItemSave) => !state.inflight && (state.status === "dirty" || state.status === "error") && state.desiredKey !== state.savedKey;
/** Starts a save when one is needed; sequence numbers only ever increase per item. */
export function beginSave(state: ItemSave): { state: ItemSave; request: SaveRequest } | null {
  if (!needsSave(state)) return null;
  const sequence = state.sequence + 1;
  return { state: { ...state, sequence, inflight: true, status: "saving" }, request: { selectedKey: state.desiredKey, expectedRevision: state.revision, clientSequence: sequence } };
}
/** Server acknowledged the request. A newer selection made meanwhile stays dirty. */
export function ackSave(state: ItemSave, request: SaveRequest, answerRevision: number): ItemSave {
  const next = { ...state, inflight: false, revision: answerRevision, savedKey: request.selectedKey };
  return { ...next, status: next.desiredKey === next.savedKey ? "saved" : "dirty" };
}
export function failSave(state: ItemSave): ItemSave { return { ...state, inflight: false, status: "error" }; }
/** 409 stale_answer: adopt the refetched server value. */
export function adoptServer(state: ItemSave, item: ServerItem): ItemSave {
  return { savedKey: item.selectedKey, desiredKey: item.selectedKey, revision: item.answerRevision, sequence: Math.max(state.sequence, item.clientSequence), status: "saved", inflight: false, refreshed: state.desiredKey !== item.selectedKey };
}
export const SAVE_LABEL: Record<ItemStatus, string> = { saved: "Đã lưu", dirty: "Đang lưu…", saving: "Đang lưu…", error: "Chưa lưu – thử lại" };
export const saveLabel = (state: ItemSave) => SAVE_LABEL[state.status];
export const RETRY_BASE_MS = 1000;
export const RETRY_MAX_MS = 15000;
/** Backoff before auto-retry number `attempt` (0-based). */
export const retryDelay = (attempt: number) => Math.min(RETRY_MAX_MS, RETRY_BASE_MS * 2 ** Math.max(0, Math.min(attempt, 6)));
/** Retry automatically only for network failures and 5xx/429/408; 4xx needs a manual retry. */
export const isRetryableStatus = (status: number | null) => status === null || status >= 500 || status === 429 || status === 408;
export const unansweredCount = (items: readonly { desiredKey: string | null }[]) => items.filter(item => !item.desiredKey).length;
export const unsavedCount = (states: readonly ItemSave[]) => states.filter(state => state.status !== "saved").length;
export const failedCount = (states: readonly ItemSave[]) => states.filter(state => state.status === "error").length;

/* ---------- scores ---------- */
export function formatScore(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "Chờ chấm";
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n.toLocaleString("vi-VN", { maximumFractionDigits: 2 }) : "Chờ chấm";
}
/** `score` null means not graded yet: never rendered as 0. */
export function scoreText(score: string | number | null | undefined, maxScore: string | number | null | undefined): string {
  if (score === null || score === undefined || score === "") return "Chờ chấm";
  return maxScore === null || maxScore === undefined || maxScore === "" ? formatScore(score) : `${formatScore(score)} / ${formatScore(maxScore)}`;
}
export type Denominators = { enrolled: number; started: number; submitted: number; graded: number; pending: number };
export const denominatorsText = (d: Denominators) => `đã nộp ${d.submitted} / đã chấm ${d.graded} / chờ chấm ${d.pending} / tổng ${d.enrolled}`;

/* ---------- assignment form ---------- */
export const TIMEZONES = ["Asia/Ho_Chi_Minh", "Asia/Bangkok", "Asia/Singapore", "Asia/Tokyo", "UTC"] as const;
export const DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh";
function zoneOffsetMs(ts: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }).formatToParts(new Date(ts));
  const get = (type: string) => Number(parts.find(part => part.type === type)?.value);
  return Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second")) - Math.floor(ts / 1000) * 1000;
}
/** Wall-clock `YYYY-MM-DDTHH:mm` in the given IANA zone to an ISO instant; null when malformed. */
export function zonedToIso(local: string, timeZone: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(local);
  if (!match) return null;
  const [y, mo, d, h, mi] = match.slice(1).map(Number);
  const wall = Date.UTC(y, mo - 1, d, h, mi);
  if (new Date(wall).getUTCMonth() !== mo - 1) return null;
  try {
    let ts = wall - zoneOffsetMs(wall, timeZone);
    ts = wall - zoneOffsetMs(ts, timeZone);
    return new Date(ts).toISOString();
  } catch { return null; }
}
/** Instant to `YYYY-MM-DDTHH:mm` wall-clock in the zone (for datetime-local defaults). */
export function isoToZoned(iso: string, timeZone: string): string {
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return "";
  return new Date(ts + zoneOffsetMs(ts, timeZone)).toISOString().slice(0, 16);
}
export type ScoreRelease = "immediate" | "after_close" | "manual";
export type SolutionRelease = "never" | "after_close" | "manual";
export const SCORE_RELEASE_LABEL: Record<ScoreRelease, string> = { immediate: "Ngay sau khi chấm", after_close: "Sau khi đóng bài", manual: "Giáo viên công bố thủ công" };
export const SOLUTION_RELEASE_LABEL: Record<SolutionRelease, string> = { never: "Không công bố đáp án", after_close: "Sau khi đóng bài", manual: "Giáo viên công bố thủ công" };
export type AssignmentForm = { examVersionId: string; title: string; instructions: string; opensAt: string; closesAt: string; timezone: string; timeLimitMinutes: string; maxAttempts: string; scoreRelease: ScoreRelease; solutionRelease: SolutionRelease };
export const emptyAssignmentForm = (): AssignmentForm => ({ examVersionId: "", title: "", instructions: "", opensAt: "", closesAt: "", timezone: DEFAULT_TIMEZONE, timeLimitMinutes: "", maxAttempts: "1", scoreRelease: "manual", solutionRelease: "manual" });
export type AssignmentBody = { examVersionId: string; title: string; instructions?: string; opensAt: string; closesAt?: string; timeLimitSeconds?: number; maxAttempts: number; timezone: string; scoreRelease: ScoreRelease; solutionRelease: SolutionRelease };
export function buildAssignmentBody(form: AssignmentForm): { ok: true; body: AssignmentBody } | { ok: false; error: string } {
  const title = form.title.trim();
  if (!form.examVersionId) return { ok: false, error: "Hãy chọn phiên bản đề đã xuất bản." };
  if (!title) return { ok: false, error: "Hãy nhập tiêu đề bài giao." };
  if (title.length > 200) return { ok: false, error: "Tiêu đề tối đa 200 ký tự." };
  const opensAt = zonedToIso(form.opensAt, form.timezone);
  if (!opensAt) return { ok: false, error: "Hãy chọn thời điểm mở bài." };
  let closesAt: string | undefined;
  if (form.closesAt) {
    const closes = zonedToIso(form.closesAt, form.timezone);
    if (!closes) return { ok: false, error: "Thời điểm đóng bài không hợp lệ." };
    if (Date.parse(closes) <= Date.parse(opensAt)) return { ok: false, error: "Thời điểm đóng phải sau thời điểm mở." };
    closesAt = closes;
  }
  let timeLimitSeconds: number | undefined;
  if (form.timeLimitMinutes.trim()) {
    const minutes = Number(form.timeLimitMinutes);
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 600) return { ok: false, error: "Thời gian làm bài từ 1 đến 600 phút." };
    timeLimitSeconds = minutes * 60;
  }
  const maxAttempts = Number(form.maxAttempts);
  if (!Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 20) return { ok: false, error: "Số lần làm tối đa từ 1 đến 20." };
  const instructions = form.instructions.trim();
  return { ok: true, body: { examVersionId: form.examVersionId, title, ...(instructions ? { instructions } : {}), opensAt, ...(closesAt ? { closesAt } : {}), ...(timeLimitSeconds ? { timeLimitSeconds } : {}), maxAttempts, timezone: form.timezone, scoreRelease: form.scoreRelease, solutionRelease: form.solutionRelease } };
}
/** Override form: score within [0, max] (comma or dot decimal) and a mandatory reason. */
export function buildOverrideBody(scoreText: string, reasonText: string, maxScore: string | number | null): { ok: true; body: { score: number; reason: string } } | { ok: false; error: string } {
  const score = Number(scoreText.trim().replace(",", "."));
  const max = maxScore === null ? NaN : Number(maxScore);
  if (!scoreText.trim() || !Number.isFinite(score) || score < 0) return { ok: false, error: "Hãy nhập điểm hợp lệ (không âm)." };
  if (Number.isFinite(max) && score > max) return { ok: false, error: `Điểm tối đa là ${formatScore(max)}.` };
  const reason = reasonText.trim();
  if (!reason) return { ok: false, error: "Hãy nhập lý do điều chỉnh điểm." };
  if (reason.length > 1000) return { ok: false, error: "Lý do tối đa 1000 ký tự." };
  return { ok: true, body: { score, reason } };
}
export type AssignmentStatus = "draft" | "published" | "closed" | "archived";
export const ASSIGNMENT_STATUS: Record<AssignmentStatus, [string, "info" | "warn" | "error" | undefined]> = { draft: ["Bản nháp", "warn"], published: ["Đang giao", undefined], closed: ["Đã đóng", "error"], archived: ["Đã lưu trữ", "warn"] };
export const GRADING_LABEL: Record<string, [string, "info" | "warn" | "error" | undefined]> = { not_started: ["Chưa làm", "warn"], not_submitted: ["Chưa nộp", "warn"], pending: ["Chờ chấm", "info"], graded: ["Đã chấm", undefined], void: ["Đã hủy", "error"] };
export const SUBMISSION_REASON: Record<string, string> = { student: "Học sinh nộp", deadline: "Tự nộp khi hết giờ", teacher: "Giáo viên nộp" };

/** Error codes meaning the attempt can no longer be edited. */
export const isAttemptOver = (code: string) => code === "attempt_expired" || code === "attempt_closed";
