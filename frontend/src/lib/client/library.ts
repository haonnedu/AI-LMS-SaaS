// Pure helpers for the teacher library. No DOM, no path aliases (loaded directly by node:test).
export const QUERY_MAX = 2000;
export const K_MIN = 1;
export const K_MAX = 20;
export const K_DEFAULT = 8;

export type QueryCheck = { ok: true; query: string } | { ok: false; error: string };
export function validateQuery(raw: string): QueryCheck {
  const query = raw.trim();
  if (!query) return { ok: false, error: "Hãy nhập nội dung cần tìm." };
  if (query.length > QUERY_MAX) return { ok: false, error: `Nội dung tìm kiếm tối đa ${QUERY_MAX} ký tự.` };
  return { ok: true, query };
}
export function validateK(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= K_MIN && value <= K_MAX ? value : null;
}
/** Request body for the retrieval query; null when input is invalid. */
export function buildQueryBody(raw: string, documentIds: string[], k: number = K_DEFAULT) {
  const checked = validateQuery(raw);
  const kk = validateK(k);
  if (!checked.ok || kk === null) return null;
  const body: { query: string; k: number; documentIds?: string[] } = { query: checked.query, k: kk };
  if (documentIds.length) body.documentIds = [...documentIds];
  return body;
}

type Located = { pageNo: number | null; sectionPath: string | null };
/** "Trang 3 · Chương 1 > Bài 2" style location, or "" when unknown. */
export function formatLocation(item: Located): string {
  const parts: string[] = [];
  if (item.pageNo !== null && item.pageNo !== undefined) parts.push(`Trang ${item.pageNo}`);
  if (item.sectionPath) parts.push(item.sectionPath);
  return parts.join(" · ");
}
/** Citation label: the server label when present, otherwise built from the real title and location. Never invents data. */
export function citationLabel(item: Located & { citation?: unknown }, title?: string): string {
  if (typeof item.citation === "string" && item.citation.trim()) return item.citation.trim();
  return [title, formatLocation(item)].filter(Boolean).join(", ");
}

export type Grouped<T> = { documentId: string; items: T[] };
/** Groups items by document, ordered by each document's first (best-ranked) appearance. */
export function groupByDocument<T extends { documentId: string }>(items: T[]): Grouped<T>[] {
  const groups = new Map<string, Grouped<T>>();
  for (const item of items) {
    const group = groups.get(item.documentId);
    if (group) group.items.push(item);
    else groups.set(item.documentId, { documentId: item.documentId, items: [item] });
  }
  return [...groups.values()];
}
export function titleMap(docs: { id: string; fileName: string }[]): Record<string, string> {
  return Object.fromEntries(docs.map(doc => [doc.id, doc.fileName]));
}
export function toggleId(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id];
}
/** Appends a chunk page, dropping any chunk already present. */
export function mergeById<T extends { id: string }>(current: T[], next: T[]): T[] {
  const seen = new Set(current.map(x => x.id));
  return [...current, ...next.filter(x => !seen.has(x.id))];
}
/** Distinct sorted grades of units. */
export function sortUnits<T extends { sortOrder: number; unitCode: string }>(units: T[]): T[] {
  return [...units].sort((a, b) => a.sortOrder - b.sortOrder || a.unitCode.localeCompare(b.unitCode));
}
export const PILOT_PROVENANCE = "seed:pilot-draft";
export const isPilotDraft = (provenance: string) => provenance === PILOT_PROVENANCE;
