// Pure helpers for AI drafts, provenance, exams and exports. No timers, no DOM, never logs payloads.
export type Purpose = "lesson_plan" | "study_guide" | "questions";
export type Cognitive = "remember" | "understand" | "apply" | "analyze";
export type DraftRequest = {
  purpose: Purpose; curriculumUnitId: string; grade: number; subject: string; objectives: string[];
  contentItemId?: string; durationMinutes?: number; documentIds?: string[]; count?: number; cognitiveLevel?: Cognitive; title?: string;
};
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const MAX_OBJECTIVES = 10;
export const MAX_OBJECTIVE_CHARS = 300;
export const MAX_DRAFT_DOCUMENTS = 20;
export const MAX_DRAFT_COUNT = 20;

/** One objective per non-empty line, trimmed, de-duplicated. */
export function parseObjectives(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    const value = line.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, "").trim();
    if (value && !seen.has(value)) { seen.add(value); out.push(value); }
  }
  return out;
}
export type DraftForm = {
  purpose: Purpose; curriculumUnitId: string; grade: number | null; subject: string; objectivesText: string; duration: string;
  documentIds: string[]; contentItemId?: string; count?: string; cognitiveLevel?: Cognitive | ""; title?: string;
};
export type Validated<T> = { ok: true; value: T } | { ok: false; message: string };
export function buildDraftRequest(form: DraftForm): Validated<DraftRequest> {
  if (!UUID.test(form.curriculumUnitId)) return { ok: false, message: "Hãy chọn môn học, lớp và đơn vị kiến thức." };
  if (!form.subject || !form.grade || !Number.isInteger(form.grade) || form.grade < 1 || form.grade > 12) return { ok: false, message: "Hãy chọn môn học và lớp." };
  const objectives = parseObjectives(form.objectivesText);
  if (objectives.length === 0) return { ok: false, message: "Hãy nhập ít nhất một mục tiêu bài học." };
  if (objectives.length > MAX_OBJECTIVES) return { ok: false, message: `Tối đa ${MAX_OBJECTIVES} mục tiêu.` };
  if (objectives.some(o => o.length > MAX_OBJECTIVE_CHARS)) return { ok: false, message: `Mỗi mục tiêu tối đa ${MAX_OBJECTIVE_CHARS} ký tự.` };
  if (form.documentIds.length > MAX_DRAFT_DOCUMENTS || form.documentIds.some(id => !UUID.test(id))) return { ok: false, message: "Danh sách tài liệu nguồn không hợp lệ." };
  const request: DraftRequest = { purpose: form.purpose, curriculumUnitId: form.curriculumUnitId.toLowerCase(), grade: form.grade, subject: form.subject, objectives };
  if (form.duration.trim()) {
    const minutes = Number(form.duration);
    if (!Number.isInteger(minutes) || minutes < 5 || minutes > 600) return { ok: false, message: "Thời lượng phải từ 5 đến 600 phút." };
    request.durationMinutes = minutes;
  }
  if (form.documentIds.length) request.documentIds = [...new Set(form.documentIds)];
  if (form.contentItemId) { if (!UUID.test(form.contentItemId)) return { ok: false, message: "Nội dung không hợp lệ." }; request.contentItemId = form.contentItemId.toLowerCase(); }
  if (form.count && form.count.trim()) {
    const count = Number(form.count);
    if (!Number.isInteger(count) || count < 1 || count > MAX_DRAFT_COUNT) return { ok: false, message: `Số câu phải từ 1 đến ${MAX_DRAFT_COUNT}.` };
    request.count = count;
  }
  if (form.cognitiveLevel) request.cognitiveLevel = form.cognitiveLevel;
  if (form.title && form.title.trim()) request.title = form.title.trim().slice(0, 200);
  return { ok: true, value: request };
}

/* ---------- generation job outcome ---------- */
export type GenerationJobLike = { validationStatus: "pending" | "valid" | "invalid" | "failed"; errorCode: string | null; reasons: string[]; contentItemId?: string | null; revisionNo?: number | null; questionIds?: string[] };
export type Outcome =
  | { kind: "pending" }
  | { kind: "success"; contentItemId: string | null; revisionNo: number | null; questionIds: string[] }
  | { kind: "invalid"; message: string; reasons: string[] }
  | { kind: "unavailable"; message: string }
  | { kind: "failed"; message: string; code: string };
export const AI_UNAVAILABLE_MESSAGE = "AI tạm không khả dụng, bạn vẫn soạn tay được";
export const AI_UNAVAILABLE_CODES = ["ai_unavailable", "provider_unavailable"];
export const isAiUnavailableCode = (code: string | null | undefined) => !!code && AI_UNAVAILABLE_CODES.includes(code);
export function generationOutcome(job: GenerationJobLike): Outcome {
  if (job.validationStatus === "pending" && !job.errorCode) return { kind: "pending" };
  if (isAiUnavailableCode(job.errorCode)) return { kind: "unavailable", message: AI_UNAVAILABLE_MESSAGE };
  if (job.validationStatus === "invalid") return { kind: "invalid", message: "Bản nháp AI không đạt kiểm tra nên không được lưu.", reasons: job.reasons };
  if (job.validationStatus === "failed" || job.errorCode) return { kind: "failed", message: "Không tạo được bản nháp AI. Bạn vẫn soạn tay được.", code: job.errorCode || "generation_failed" };
  return { kind: "success", contentItemId: job.contentItemId ?? null, revisionNo: job.revisionNo ?? null, questionIds: job.questionIds ?? [] };
}

/* ---------- provenance ---------- */
export type SourceStatus = "active" | "superseded" | "withdrawn";
export const SOURCE_STATUS: Record<SourceStatus, { label: string; tone: "info" | "warn" | "error" | undefined }> = {
  active: { label: "Còn hiệu lực", tone: undefined },
  superseded: { label: "Đã được thay thế", tone: "warn" },
  withdrawn: { label: "Nguồn không còn tồn tại", tone: "error" },
};
export const provenanceStatus = (status: string) => SOURCE_STATUS[status as SourceStatus] || SOURCE_STATUS.withdrawn;
export type SourceLike = { snippet: string | null; status: string; chunkId: string | null; pageNo: number | null; sectionPath: string | null };
/** Withdrawn sources never show a snippet: no guessed text. */
export const sourceSnippet = (source: SourceLike) => source.status === "withdrawn" ? null : source.snippet;
export const canViewSource = (source: SourceLike) => source.status !== "withdrawn" && !!source.chunkId;
export function sourceLocation(source: SourceLike) {
  const parts: string[] = [];
  if (source.pageNo) parts.push(`trang ${source.pageNo}`);
  if (source.sectionPath) parts.push(source.sectionPath);
  return parts.join(" · ");
}
export const APPROVE_ERRORS: Record<string, string> = {
  citations_unresolved: "Không thể duyệt: còn trích dẫn chưa xác minh được nguồn. Hãy kiểm tra các nguồn bị rút hoặc không tìm thấy rồi sửa nội dung.",
};
export function approveMessage(code: string | undefined, fallback: string) { return (code && APPROVE_ERRORS[code]) || fallback; }

/* ---------- exports ---------- */
export type ExportFormat = "docx" | "pdf";
export type Audience = "teacher" | "student";
export const AUDIENCE_LABEL: Record<Audience, string> = { teacher: "giáo viên", student: "học sinh" };
const stripDiacritics = (value: string) => value.normalize("NFD").replace(/\p{M}/gu, "").replace(/đ/g, "d").replace(/Đ/g, "D");
/** Safe download name, e.g. "de-kiem-tra-giua-ky-giao-vien.docx". */
export function exportFileName(title: string, audience: Audience, format: ExportFormat) {
  const slug = stripDiacritics(title).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60).replace(/-+$/g, "") || "tai-lieu";
  return `${slug}-${audience === "teacher" ? "giao-vien" : "hoc-sinh"}.${format}`;
}
export const PDF_NOTE = "PDF chưa hỗ trợ tiếng Việt, dùng DOCX";
export function exportFailureMessage(code: string | null | undefined, format: ExportFormat) {
  const base = `Xuất tệp thất bại${code ? ` (${code})` : ""}.`;
  return format === "pdf" ? `${base} ${PDF_NOTE}.` : base;
}
export type ExportJobLike = { status: "queued" | "succeeded" | "failed"; downloadUrl?: string | null; downloadExpiresAt?: string | null; errorCode: string | null };
export const isExportTerminal = (job: ExportJobLike) => job.status === "succeeded" || job.status === "failed";
/** Only http(s) URLs are offered as download links. */
export function safeDownloadUrl(url: string | null | undefined) {
  if (!url) return null;
  try { const parsed = new URL(url, "http://localhost"); return parsed.protocol === "https:" || parsed.protocol === "http:" ? url : null; } catch { return null; }
}
export function expiryLabel(expiresAt: string | null | undefined, now = Date.now()) {
  if (!expiresAt) return "";
  const time = Date.parse(expiresAt);
  if (!Number.isFinite(time)) return "";
  const minutes = Math.floor((time - now) / 60000);
  if (minutes <= 0) return "Liên kết đã hết hạn, hãy xuất lại";
  return minutes >= 60 ? `Liên kết còn hiệu lực khoảng ${Math.floor(minutes / 60)} giờ` : `Liên kết còn hiệu lực ${minutes} phút`;
}

/* ---------- exams ---------- */
export type SelectionReportLike = {
  ok?: boolean; seed?: string; selected?: number;
  missingSlots: { cognitiveLevel: Cognitive; curriculumUnitId: string; difficulty: number | null; index: number; partCode: string; reason: string }[];
  suggestedGeneration: { cognitiveLevel: Cognitive; count: number; curriculumUnitId: string; difficulty: number | null; purpose: "questions" }[];
};
/** Seed is optional; blank means "let the server choose". */
export function buildExamFromBlueprint(blueprintVersionId: string, seed: string, title: string): Validated<Record<string, string>> {
  if (!UUID.test(blueprintVersionId)) return { ok: false, message: "Phiên bản ma trận không hợp lệ." };
  const body: Record<string, string> = { blueprintVersionId };
  if (seed.trim()) { if (!/^[A-Za-z0-9_-]{1,64}$/.test(seed.trim())) return { ok: false, message: "Seed chỉ gồm chữ, số, gạch ngang hoặc gạch dưới (tối đa 64 ký tự)." }; body.seed = seed.trim(); }
  if (title.trim()) body.title = title.trim().slice(0, 200);
  return { ok: true, value: body };
}
/** Extracts the selection report from a 409 insufficient_pool error detail. */
export function reportFromError(detail: unknown): SelectionReportLike | null {
  if (typeof detail !== "object" || detail === null) return null;
  const report = (detail as { selectionReport?: unknown }).selectionReport;
  if (typeof report !== "object" || report === null) return null;
  const r = report as Partial<SelectionReportLike>;
  return { ...r, missingSlots: Array.isArray(r.missingSlots) ? r.missingSlots : [], suggestedGeneration: Array.isArray(r.suggestedGeneration) ? r.suggestedGeneration : [] };
}
/** Maps suggested generation entries to question-draft requests (one per suggestion; count capped). */
export function suggestionsToRequests(report: SelectionReportLike, context: { grade: number; subject: string }): DraftRequest[] {
  return report.suggestedGeneration.filter(s => UUID.test(s.curriculumUnitId) && s.count > 0).map(s => ({
    purpose: "questions" as const, curriculumUnitId: s.curriculumUnitId, grade: context.grade, subject: context.subject,
    objectives: ["Bổ sung câu hỏi cho ô còn thiếu của ma trận đề"], count: Math.min(MAX_DRAFT_COUNT, Math.max(1, Math.trunc(s.count))), cognitiveLevel: s.cognitiveLevel,
  }));
}
export type ManualPick = { id: string; points: string };
export function buildManualExam(title: string, picks: ManualPick[]): Validated<{ title: string; questionIds: string[]; points: number[] }> {
  if (!title.trim()) return { ok: false, message: "Hãy nhập tên đề." };
  if (picks.length === 0) return { ok: false, message: "Hãy chọn ít nhất một câu hỏi." };
  if (picks.length > 200) return { ok: false, message: "Tối đa 200 câu hỏi." };
  const points: number[] = [];
  for (const pick of picks) {
    const value = Number(pick.points);
    if (!UUID.test(pick.id)) return { ok: false, message: "Câu hỏi không hợp lệ." };
    if (!Number.isFinite(value) || value <= 0 || value > 100) return { ok: false, message: "Điểm mỗi câu phải lớn hơn 0 và tối đa 100." };
    points.push(Math.round(value * 100) / 100);
  }
  return { ok: true, value: { title: title.trim().slice(0, 200), questionIds: picks.map(p => p.id), points } };
}
export const totalPoints = (picks: ManualPick[]) => Math.round(picks.reduce((sum, p) => sum + (Number(p.points) || 0), 0) * 100) / 100;
export const EXAM_STATUS: Record<"draft" | "published" | "archived", [string, "warn" | "error" | undefined]> = { draft: ["Bản nháp", "warn"], published: ["Đã xuất bản", undefined], archived: ["Đã lưu trữ", "warn"] };
