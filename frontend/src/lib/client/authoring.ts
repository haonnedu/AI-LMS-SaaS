// Pure helpers for the authoring UI (content editor, question bank, blueprints). No timers, no DOM.

/* ---------- content body ---------- */
export const BLOCK_TYPES = ["paragraph", "list", "objective", "activity", "note"] as const;
export type BlockType = (typeof BLOCK_TYPES)[number];
export const BLOCK_LABEL: Record<BlockType, string> = { paragraph: "Đoạn văn", list: "Danh sách", objective: "Mục tiêu", activity: "Hoạt động", note: "Ghi chú" };
export type Citation = { chunkId: string; label: string };
export type Block = { type: BlockType; text: string; citations: Citation[] };
export type Section = { heading: string; blocks: Block[] };
export type ContentBody = { sections: Section[] };
export const MAX_SECTIONS = 50;
export const MAX_BLOCKS = 100;

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const newBlock = (type: BlockType = "paragraph"): Block => ({ type, text: "", citations: [] });
export const newSection = (): Section => ({ heading: "", blocks: [newBlock()] });
export const emptyBody = (): ContentBody => ({ sections: [newSection()] });

/** Tolerant reader: unknown shapes become an editable body; unknown block types fall back to paragraph. */
export function normalizeBody(raw: unknown): ContentBody {
  if (!isObject(raw) || !Array.isArray(raw.sections)) return emptyBody();
  const sections: Section[] = raw.sections.filter(isObject).map(section => ({
    heading: typeof section.heading === "string" ? section.heading : "",
    blocks: (Array.isArray(section.blocks) ? section.blocks : []).filter(isObject).map(block => ({
      type: (BLOCK_TYPES as readonly string[]).includes(block.type as string) ? (block.type as BlockType) : "paragraph",
      text: typeof block.text === "string" ? block.text : "",
      citations: (Array.isArray(block.citations) ? block.citations : []).filter(isObject)
        .filter(c => typeof c.chunkId === "string" && UUID.test(c.chunkId))
        .map(c => ({ chunkId: c.chunkId as string, label: typeof c.label === "string" ? c.label : "" })),
    })),
  }));
  return sections.length ? { sections } : emptyBody();
}
/** Canonical payload for PUT draft / POST revision. */
export const buildBody = (body: ContentBody): ContentBody => normalizeBody(body);
/** Stable string used to detect real edits. */
export const bodyKey = (body: ContentBody): string => JSON.stringify(buildBody(body));

export function moveItem<T>(items: readonly T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) return items.slice();
  const next = items.slice();
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}
export const replaceAt = <T,>(items: readonly T[], index: number, value: T): T[] => items.map((item, i) => i === index ? value : item);
export const removeAt = <T,>(items: readonly T[], index: number): T[] => items.filter((_, i) => i !== index);
export function bodyStats(body: ContentBody) {
  const blocks = body.sections.reduce((n, s) => n + s.blocks.length, 0);
  const chars = body.sections.reduce((n, s) => n + s.heading.length + s.blocks.reduce((m, b) => m + b.text.length, 0), 0);
  return { sections: body.sections.length, blocks, chars };
}

/* ---------- autosave state machine ---------- */
export const AUTOSAVE_DELAY_MS = 3000;
export type SavePhase = "idle" | "dirty" | "saving" | "saved" | "error" | "conflict";
export type SaveState = { phase: SavePhase; revisionNo: number; editSeq: number; savedSeq: number; inFlightSeq: number | null; savedAt: string | null; latestRevisionNo: number | null };
export type SaveEvent =
  | { type: "edit" }
  | { type: "saveStart" }
  | { type: "saveOk"; revisionNo: number; savedAt: string }
  | { type: "saveFail" }
  | { type: "conflict"; latestRevisionNo: number | null }
  | { type: "reset"; revisionNo: number };
export const initialSave = (revisionNo: number): SaveState => ({ phase: "idle", revisionNo, editSeq: 0, savedSeq: 0, inFlightSeq: null, savedAt: null, latestRevisionNo: null });
/** A save may start only for unsaved edits, never while one is in flight, and never over a conflict. */
export const canSave = (state: SaveState): boolean => state.inFlightSeq === null && state.phase !== "conflict" && state.editSeq > state.savedSeq;
/** A debounce timer should be armed only while edits are waiting. */
export const shouldSchedule = (state: SaveState): boolean => state.phase === "dirty";
export function saveReducer(state: SaveState, event: SaveEvent): SaveState {
  switch (event.type) {
    case "edit": {
      const editSeq = state.editSeq + 1;
      if (state.phase === "conflict") return { ...state, editSeq };
      return { ...state, editSeq, phase: state.inFlightSeq !== null ? "saving" : "dirty" };
    }
    case "saveStart":
      return canSave(state) ? { ...state, phase: "saving", inFlightSeq: state.editSeq } : state;
    case "saveOk": {
      if (state.inFlightSeq === null) return state;
      const savedSeq = state.inFlightSeq;
      return { ...state, revisionNo: event.revisionNo, savedAt: event.savedAt, savedSeq, inFlightSeq: null, phase: state.editSeq > savedSeq ? "dirty" : "saved" };
    }
    case "saveFail":
      return { ...state, inFlightSeq: null, phase: "error" };
    case "conflict":
      return { ...state, inFlightSeq: null, phase: "conflict", latestRevisionNo: event.latestRevisionNo };
    case "reset":
      return initialSave(event.revisionNo);
  }
}
export function hhmm(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
export function saveLabel(state: SaveState, formatTime: (iso: string) => string = hhmm): string {
  switch (state.phase) {
    case "dirty": return "Chưa lưu";
    case "saving": return "Đang lưu…";
    case "saved": return state.savedAt ? `Đã lưu lúc ${formatTime(state.savedAt)}` : "Đã lưu";
    case "error": return "Lỗi lưu";
    case "conflict": return "Xung đột bản nháp";
    default: return state.savedAt ? `Đã lưu lúc ${formatTime(state.savedAt)}` : "";
  }
}
export const conflictMessage = (latestRevisionNo: number | null) => latestRevisionNo === null ? "Bản nháp đã được sửa ở nơi khác." : `Bản nháp đã được sửa ở nơi khác (bản ${latestRevisionNo})`;
/** Extracts latestRevisionNo from a 409 revision_conflict error detail. */
export function conflictRevision(detail: unknown): number | null {
  if (!isObject(detail)) return null;
  const n = detail.latestRevisionNo;
  return typeof n === "number" && Number.isInteger(n) && n > 0 ? n : null;
}

/* ---------- questions ---------- */
export const COGNITIVE_LEVELS = ["remember", "understand", "apply", "analyze"] as const;
export type Cognitive = (typeof COGNITIVE_LEVELS)[number];
export const COGNITIVE_LABEL: Record<Cognitive, string> = { remember: "Nhận biết", understand: "Thông hiểu", apply: "Vận dụng", analyze: "Phân tích" };
export const CHOICE_KEYS = ["A", "B", "C", "D", "E"] as const;
export type ChoiceKey = (typeof CHOICE_KEYS)[number];
export type QuestionForm = { stem: string; choices: string[]; correctKey: ChoiceKey | ""; difficulty: string; cognitiveLevel: Cognitive; curriculumUnitId: string; explanation: string };
export const emptyQuestionForm = (): QuestionForm => ({ stem: "", choices: ["", "", ""], correctKey: "", difficulty: "", cognitiveLevel: "remember", curriculumUnitId: "", explanation: "" });
export type QuestionCheck = { ok: true } | { ok: false; error: string };
export function validateQuestionForm(form: QuestionForm): QuestionCheck {
  if (!form.stem.trim()) return { ok: false, error: "Hãy nhập nội dung câu hỏi." };
  if (form.choices.length < 3 || form.choices.length > 5) return { ok: false, error: "Câu hỏi cần từ 3 đến 5 lựa chọn." };
  if (form.choices.some(c => !c.trim())) return { ok: false, error: "Mỗi lựa chọn cần có nội dung." };
  if (!form.correctKey || CHOICE_KEYS.indexOf(form.correctKey) >= form.choices.length) return { ok: false, error: "Hãy chọn đáp án đúng." };
  if (form.difficulty && !/^[1-5]$/.test(form.difficulty)) return { ok: false, error: "Độ khó phải từ 1 đến 5." };
  return { ok: true };
}
export function buildQuestionBody(form: QuestionForm, expectedRevisionNo?: number) {
  return {
    itemType: "single_choice" as const,
    stem: form.stem.trim(),
    choices: form.choices.map((text, i) => ({ key: CHOICE_KEYS[i], text: text.trim() })),
    correctKey: form.correctKey || null,
    difficulty: form.difficulty ? Number(form.difficulty) : null,
    cognitiveLevel: form.cognitiveLevel,
    curriculumUnitId: form.curriculumUnitId || null,
    explanation: form.explanation.trim() || null,
    ...(expectedRevisionNo === undefined ? {} : { expectedRevisionNo }),
  };
}
export function questionFormFrom(q: { stem: string; choices: { key: string; text: string }[]; correctKey: string | null; difficulty: number | null; cognitiveLevel: Cognitive; curriculumUnitId: string | null; explanation: string | null }): QuestionForm {
  const sorted = q.choices.slice().sort((a, b) => a.key.localeCompare(b.key));
  return { stem: q.stem, choices: sorted.map(c => c.text), correctKey: (CHOICE_KEYS as readonly string[]).includes(q.correctKey || "") ? (q.correctKey as ChoiceKey) : "", difficulty: q.difficulty === null ? "" : String(q.difficulty), cognitiveLevel: q.cognitiveLevel, curriculumUnitId: q.curriculumUnitId || "", explanation: q.explanation || "" };
}
/** Query string for GET /questions from filter state; empty values are dropped. */
export function questionQuery(filters: Record<string, string>, cursor?: string | null, limit = 25): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value.trim()) params.set(key, value.trim());
  params.set("limit", String(limit));
  if (cursor) params.set("cursor", cursor);
  return "?" + params.toString();
}

/* ---------- CSV preview ---------- */
export const CSV_COLUMNS = ["stem", "choiceA", "choiceB", "choiceC", "choiceD", "choiceE", "correct", "difficulty", "cognitive", "unitCode", "explanation"] as const;
export const CSV_MAX_BYTES = 2097152;
export const CSV_MAX_ROWS = 2000;
/** RFC 4180 parser (quotes, doubled quotes, CRLF). Never throws; unterminated quotes consume the rest. */
export function parseCsv(input: string): string[][] {
  const text = input.charCodeAt(0) === 0xfeff ? input.slice(1) : input;
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else quoted = false; }
      else cell += ch;
    } else if (ch === '"' && cell === "") quoted = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); cell = ""; rows.push(row); row = [];
    } else cell += ch;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return rows;
}
export type CsvPreview = { ok: boolean; headerOk: boolean; rowCount: number; rows: string[][]; problems: { row: number; message: string }[] };
/** Cheap client-side look at an import file; the server remains authoritative. Problem rows are 1-based file lines. */
export function previewCsv(text: string, maxRows = 5): CsvPreview {
  const all = parseCsv(text);
  if (all.length === 0) return { ok: false, headerOk: false, rowCount: 0, rows: [], problems: [{ row: 1, message: "Tệp CSV không có dữ liệu." }] };
  const header = all[0].map(c => c.trim());
  const headerOk = header.length === CSV_COLUMNS.length && CSV_COLUMNS.every((c, i) => header[i] === c);
  const problems: { row: number; message: string }[] = [];
  if (!headerOk) problems.push({ row: 1, message: "Dòng tiêu đề phải là: " + CSV_COLUMNS.join(",") });
  const data = all.slice(1).filter(r => r.some(c => c.trim()));
  if (headerOk) {
    all.slice(1).forEach((r, i) => { if (r.some(c => c.trim()) && r.length !== CSV_COLUMNS.length) problems.push({ row: i + 2, message: "Số cột của dòng không đúng." }); });
    if (data.length > CSV_MAX_ROWS) problems.push({ row: CSV_MAX_ROWS + 2, message: `Tối đa ${CSV_MAX_ROWS} câu mỗi lần.` });
  }
  return { ok: headerOk && problems.length === 0, headerOk, rowCount: data.length, rows: data.slice(0, maxRows), problems };
}

/* ---------- blueprint ---------- */
export type Slot = { index: number; itemType: "single_choice"; points: number; curriculumUnitId: string; cognitiveLevel: Cognitive; difficulty?: number };
export type Part = { code: string; title: string; slots: Slot[] };
export type MatrixRow = { curriculumUnitId: string; cognitiveLevel: Cognitive; count: number };
export type BlueprintBody = { parts: Part[]; matrix: MatrixRow[] };
export const emptyBlueprintBody = (): BlueprintBody => ({ parts: [{ code: "I", title: "Phần I", slots: [] }], matrix: [] });
const level = (v: unknown): Cognitive => (COGNITIVE_LEVELS as readonly string[]).includes(v as string) ? (v as Cognitive) : "remember";
const num = (v: unknown, d = 0) => typeof v === "number" && Number.isFinite(v) ? v : typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v)) ? Number(v) : d;
/** Slot indexes are 1-based and contiguous across parts, in order. */
export function renumberSlots(body: BlueprintBody): BlueprintBody {
  let n = 0;
  return { ...body, parts: body.parts.map(part => ({ ...part, slots: part.slots.map(slot => ({ ...slot, index: ++n })) })) };
}
export function normalizeBlueprintBody(raw: unknown): BlueprintBody {
  if (!isObject(raw)) return emptyBlueprintBody();
  const parts: Part[] = (Array.isArray(raw.parts) ? raw.parts : []).filter(isObject).map((p, pi) => ({
    code: typeof p.code === "string" ? p.code : String(pi + 1),
    title: typeof p.title === "string" ? p.title : "",
    slots: (Array.isArray(p.slots) ? p.slots : []).filter(isObject).map(s => {
      const d = num(s.difficulty, 0);
      return { index: 0, itemType: "single_choice" as const, points: num(s.points, 0), curriculumUnitId: typeof s.curriculumUnitId === "string" ? s.curriculumUnitId : "", cognitiveLevel: level(s.cognitiveLevel), ...(d >= 1 && d <= 5 ? { difficulty: Math.round(d) } : {}) };
    }),
  }));
  const matrix: MatrixRow[] = (Array.isArray(raw.matrix) ? raw.matrix : []).filter(isObject).map(m => ({ curriculumUnitId: typeof m.curriculumUnitId === "string" ? m.curriculumUnitId : "", cognitiveLevel: level(m.cognitiveLevel), count: Math.max(0, Math.trunc(num(m.count, 0))) }));
  return renumberSlots({ parts: parts.length ? parts : emptyBlueprintBody().parts, matrix });
}
export const allSlots = (body: BlueprintBody): Slot[] => body.parts.flatMap(p => p.slots);
export const matrixKey = (unit: string, lvl: string) => `${unit}|${lvl}`;
/** Counts of slots per (unit, level) cell. */
export function slotCells(body: BlueprintBody): Record<string, number> {
  const cells: Record<string, number> = {};
  for (const slot of allSlots(body)) { const k = matrixKey(slot.curriculumUnitId, slot.cognitiveLevel); cells[k] = (cells[k] || 0) + 1; }
  return cells;
}
/** Matrix rows rebuilt from the slots, so the matrix cannot drift from the parts. */
export function deriveMatrix(body: BlueprintBody): MatrixRow[] {
  return Object.entries(slotCells(body)).filter(([k]) => !k.startsWith("|")).map(([k, count]) => { const [curriculumUnitId, cognitiveLevel] = k.split("|"); return { curriculumUnitId, cognitiveLevel: cognitiveLevel as Cognitive, count }; })
    .sort((a, b) => a.curriculumUnitId.localeCompare(b.curriculumUnitId) || COGNITIVE_LEVELS.indexOf(a.cognitiveLevel) - COGNITIVE_LEVELS.indexOf(b.cognitiveLevel));
}
export type BlueprintTotals = { slots: number; points: number; matrixCount: number; byLevel: Record<Cognitive, number>; mismatches: { curriculumUnitId: string; cognitiveLevel: Cognitive; slots: number; matrix: number }[] };
export function blueprintTotals(body: BlueprintBody): BlueprintTotals {
  const slots = allSlots(body);
  const byLevel: Record<Cognitive, number> = { remember: 0, understand: 0, apply: 0, analyze: 0 };
  for (const s of slots) byLevel[s.cognitiveLevel]++;
  const declared: Record<string, number> = {};
  for (const m of body.matrix) { const k = matrixKey(m.curriculumUnitId, m.cognitiveLevel); declared[k] = (declared[k] || 0) + m.count; }
  const actual = slotCells(body);
  const mismatches = [...new Set([...Object.keys(declared), ...Object.keys(actual)])].filter(k => (declared[k] || 0) !== (actual[k] || 0)).sort().map(k => { const [curriculumUnitId, cognitiveLevel] = k.split("|"); return { curriculumUnitId, cognitiveLevel: cognitiveLevel as Cognitive, slots: actual[k] || 0, matrix: declared[k] || 0 }; });
  return { slots: slots.length, points: Math.round(slots.reduce((n, s) => n + s.points, 0) * 100) / 100, matrixCount: body.matrix.reduce((n, m) => n + m.count, 0), byLevel, mismatches };
}
export function buildBlueprintBody(body: BlueprintBody): BlueprintBody {
  const clean = renumberSlots(body);
  return {
    parts: clean.parts.map(p => ({ code: p.code.trim(), title: p.title.trim(), slots: p.slots.map(s => ({ index: s.index, itemType: "single_choice" as const, points: s.points, curriculumUnitId: s.curriculumUnitId, cognitiveLevel: s.cognitiveLevel, ...(s.difficulty ? { difficulty: s.difficulty } : {}) })) })),
    matrix: clean.matrix.filter(m => m.curriculumUnitId && m.count > 0),
  };
}
