"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@/lib/api/generated";
import { jsonInit, read, RequestError } from "@/lib/client/api";
import {
  AUTOSAVE_DELAY_MS, BLOCK_LABEL, BLOCK_TYPES, buildBody, canSave, conflictMessage, conflictRevision, initialSave, MAX_BLOCKS, MAX_SECTIONS, moveItem, newBlock, newSection,
  normalizeBody, removeAt, replaceAt, saveLabel, saveReducer, shouldSchedule, type BlockType, type ContentBody, type SaveEvent, type SaveState,
} from "@/lib/client/authoring";
import { approveMessage } from "@/lib/client/generation";
import { AiDraftPanel } from "./ai-draft-panel";
import { Chip, dateTime, unitLabel, type Tone } from "./authoring-shared";
import { CitationDrawer } from "./citation-drawer";
import { ExportControls } from "./export-controls";
import { ProvenancePanel, useProvenance } from "./provenance-panel";
import { panelId, Tabs, tabId } from "./tabs";
import { ITEM_STATUS, KIND_LABEL } from "./lessons-screen";
import { Modal } from "./modal";
import { TeachingNav } from "./teaching-nav";
import { useTeaching } from "./use-teaching";
import styles from "./teaching.module.css";

type Item = components["schemas"]["ContentItemDetailDTO"];
type Revision = components["schemas"]["RevisionDTO"];
type RevisionSummary = components["schemas"]["RevisionSummaryDTO"];
const REV_STATUS: Record<Revision["status"], [string, Tone]> = { draft: ["Bản nháp", "warn"], in_review: ["Chờ duyệt", "info"], approved: ["Đã duyệt", undefined], published: ["Đã xuất bản", undefined], archived: ["Đã lưu trữ", "warn"] };

export function LessonEditorScreen({ itemId }: { itemId: string }) {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const base = workspace ? `/api/backend/workspaces/${workspace.id}/content-items/${itemId}` : "";
  const [item, setItem] = useState<Item | null>(null);
  const [body, setBody] = useState<ContentBody | null>(null);
  const [save, setSave] = useState<SaveState>(initialSave(0));
  const [revisions, setRevisions] = useState<RevisionSummary[]>([]);
  const [viewing, setViewing] = useState<Revision | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [tab, setTab] = useState("content");
  const [source, setSource] = useState<{ chunkId: string; label: string } | null>(null);
  const [loadingItem, setLoadingItem] = useState(true);
  const saveRef = useRef(save);
  const bodyRef = useRef<ContentBody | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const csrfRef = useRef(csrf);
  const flushRef = useRef<() => Promise<boolean>>(async () => false);
  useEffect(() => { csrfRef.current = csrf; }, [csrf]);

  const apply = useCallback((event: SaveEvent) => { saveRef.current = saveReducer(saveRef.current, event); setSave(saveRef.current); return saveRef.current; }, []);
  const clearTimer = useCallback(() => { if (timer.current) { clearTimeout(timer.current); timer.current = undefined; } }, []);

  const load = useCallback(async () => {
    if (!base) return;
    clearTimer();
    try {
      const [detail, list]: [Item, { items: RevisionSummary[] }] = await Promise.all([read(base), read(`${base}/revisions`)]);
      const latest = detail.latestRevision;
      const next = normalizeBody(latest?.body);
      bodyRef.current = next; setBody(next); setItem(detail); setRevisions(list.items);
      saveRef.current = initialSave(latest?.revisionNo ?? detail.latestRevisionNo); setSave(saveRef.current);
      setError("");
    } catch (e) { setError(handle(e)); }
    finally { setLoadingItem(false); }
  }, [base, handle, clearTimer]);
  // Network synchronisation on workspace change.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, [load]);
  useEffect(() => clearTimer, [clearTimer]);

  const editable = item?.latestRevision?.status === "draft";

  /** Saves the current body once; never overwrites on conflict. Returns true when nothing is left unsaved. */
  const flush = useCallback(async (): Promise<boolean> => {
    clearTimer();
    if (!base || !bodyRef.current) return false;
    if (saveRef.current.phase === "conflict") return false;
    if (!canSave(saveRef.current)) return saveRef.current.inFlightSeq === null;
    apply({ type: "saveStart" });
    try {
      const saved: { revisionNo: number; savedAt: string } = await read(`${base}/draft`, { method: "PUT", headers: { "X-CSRF-Token": csrfRef.current, "Content-Type": "application/json" }, body: JSON.stringify({ body: buildBody(bodyRef.current), expectedRevisionNo: saveRef.current.revisionNo }) }, 30000);
      const after = apply({ type: "saveOk", revisionNo: saved.revisionNo, savedAt: saved.savedAt });
      if (shouldSchedule(after)) timer.current = setTimeout(() => void flushRef.current(), AUTOSAVE_DELAY_MS);
      return after.phase === "saved";
    } catch (e) {
      if (e instanceof RequestError && e.status === 409 && e.code === "revision_conflict") apply({ type: "conflict", latestRevisionNo: conflictRevision(e.detail) });
      else { apply({ type: "saveFail" }); setError(handle(e)); }
      return false;
    }
  }, [base, apply, clearTimer, handle]);
  useEffect(() => { flushRef.current = flush; }, [flush]);

  function edit(next: ContentBody) {
    if (!editable) return;
    bodyRef.current = next; setBody(next);
    const state = apply({ type: "edit" });
    clearTimer();
    if (state.phase === "dirty") timer.current = setTimeout(() => void flush(), AUTOSAVE_DELAY_MS);
  }
  // Warn before leaving the page with unsaved edits.
  const unsaved = save.phase === "dirty" || save.phase === "saving" || save.phase === "error" || save.phase === "conflict";
  useEffect(() => {
    if (!unsaved) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsaved]);

  async function transition(action: "submit" | "approve" | "publish") {
    if (!item?.latestRevision) return;
    setBusy(true); setError("");
    try {
      if (action === "submit" && !(await flush())) { setError("Chưa thể lưu bản nháp. Hãy xử lý lỗi lưu trước khi gửi duyệt."); return; }
      const endpoint = action === "approve" && prov.data?.generationJobId ? "approve-with-provenance" : action;
      await read(`${base}/revisions/${saveRef.current.revisionNo}/${endpoint}`, jsonInit(csrf));
      await load();
    } catch (e) { setError(e instanceof RequestError && e.code === "citations_unresolved" ? approveMessage(e.code, e.message) : handle(e)); if (e instanceof RequestError && e.code === "citations_unresolved") setTab("sources"); }
    finally { setBusy(false); }
  }
  async function newDraft() {
    if (!item?.latestRevision || !bodyRef.current) return;
    setBusy(true); setError("");
    try {
      await read(`${base}/revisions`, jsonInit(csrf, { body: buildBody(bodyRef.current), expectedRevisionNo: item.latestRevision.revisionNo }));
      await load();
    } catch (e) { setError(handle(e)); }
    finally { setBusy(false); }
  }
  async function view(no: number) {
    try { setViewing(await read(`${base}/revisions/${no}`)); } catch (e) { setError(handle(e)); }
  }

  const rev = item?.latestRevision || null;
  const prov = useProvenance(base, rev?.revisionNo ?? null, rev?.status ?? "");
  const wsBase = workspace ? `/api/backend/workspaces/${workspace.id}` : "";
  const aiRevision = !!prov.data?.generationJobId;
  const published = item?.currentRevision?.status === "published" ? item.currentRevision : null;
  const label = saveLabel(save);
  const sectionCount = body?.sections.length ?? 0;
  const mutate = (fn: (current: ContentBody) => ContentBody) => { if (bodyRef.current) edit(fn(bodyRef.current)); };

  return <div className={styles.page}><div className={styles.wrap}>
    <TeachingNav current="lessons" />
    <Link className={styles.back} href="/dashboard/lessons">← Quay lại Soạn bài</Link>
    <section className={styles.card} aria-busy={phase === "loading" || loadingItem}>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {phase === "ready" && loadingItem && <p role="status">Đang tải nội dung…</p>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
      {item && rev && body && <>
        <div className={styles.head}><h1>{item.title}</h1>
          <div className={styles.actions}><Chip label={ITEM_STATUS[item.status][0]} tone={ITEM_STATUS[item.status][1]} /><Chip label={`Bản ${rev.revisionNo}: ${REV_STATUS[rev.status][0]}`} tone={REV_STATUS[rev.status][1]} /></div>
        </div>
        <p className={styles.muted}>{KIND_LABEL[item.kind]} · {item.curriculumUnitId ? unitLabel(item.curriculumUnitId) : "Chưa gắn đơn vị kiến thức"}</p>
        <div className={styles.toolbar}>
          <span className={styles.saveState} role="status" aria-live="polite" data-phase={save.phase}>{label}</span>
          {editable && (save.phase === "error" || save.phase === "dirty") && <button className="button button-secondary" onClick={() => void flush()}>Lưu ngay</button>}
          <div className={styles.actions}>
            <button type="button" className="button button-secondary" aria-expanded={aiOpen} onClick={() => setAiOpen(open => !open)}>Soạn cùng AI</button>
            {rev.status === "draft" && <button className="button button-primary" disabled={busy || save.phase === "conflict"} onClick={() => void transition("submit")}>Gửi duyệt</button>}
            {rev.status === "in_review" && <button className="button button-primary" disabled={busy} onClick={() => void transition("approve")}>Duyệt</button>}
            {rev.status === "approved" && <button className="button button-primary" disabled={busy} onClick={() => void transition("publish")}>Xuất bản</button>}
            {(rev.status === "published" || rev.status === "approved") && <button className="button button-secondary" disabled={busy} onClick={() => void newDraft()}>Tạo bản nháp mới</button>}
          </div>
        </div>
        {save.phase === "conflict" && <div role="alert" className={styles.banner}>
          <span>{conflictMessage(save.latestRevisionNo)}. Các thay đổi chưa lưu trên màn hình này chưa được ghi đè.</span>
          <button className="button button-secondary" onClick={() => void load()}>Tải lại</button>
        </div>}
        {aiRevision && (rev.status === "draft" || rev.status === "in_review") && <p className={styles.notice} role="note">Bản nháp do AI tạo, cần kiểm tra nguồn và duyệt</p>}
        {!editable && <p className={styles.notice} role="note">Bản này đang ở trạng thái “{REV_STATUS[rev.status][0]}” nên không thể chỉnh sửa. Hãy tạo bản nháp mới để tiếp tục soạn.</p>}

        <Tabs prefix="lesson" label="Nội dung bài" tabs={[{ id: "content", label: "Nội dung" }, { id: "sources", label: "Nguồn trích dẫn" }]} active={tab} onChange={setTab} />
        <div className={aiOpen ? styles.aiLayout : undefined}>
        <div style={{ minWidth: 0 }}>
        {tab === "sources" && <div role="tabpanel" id={panelId("lesson", "sources")} aria-labelledby={tabId("lesson", "sources")} tabIndex={0}>
          <ProvenancePanel data={prov.data} loading={prov.loading} error={prov.error} onView={s => setSource({ chunkId: s.chunkId || "", label: s.label })} />
        </div>}
        {tab === "content" && <div role="tabpanel" id={panelId("lesson", "content")} aria-labelledby={tabId("lesson", "content")}>
        <div onBlur={() => { if (editable) void flush(); }} className={styles.editor}>
          {body.sections.map((section, si) => <fieldset key={si} className={styles.section} disabled={!editable}>
            <legend>Phần {si + 1}</legend>
            <label className={styles.field}><span>Tiêu đề phần {si + 1}</span>
              <input value={section.heading} maxLength={300} onChange={e => mutate(b => ({ sections: replaceAt(b.sections, si, { ...section, heading: e.target.value }) }))} /></label>
            {section.blocks.map((block, bi) => <div key={bi} className={styles.block}>
              <div className={styles.blockHead}>
                <label className={styles.field}><span>Loại khối (phần {si + 1}, khối {bi + 1})</span>
                  <select value={block.type} onChange={e => mutate(b => ({ sections: replaceAt(b.sections, si, { ...section, blocks: replaceAt(section.blocks, bi, { ...block, type: e.target.value as BlockType }) }) }))}>
                    {BLOCK_TYPES.map(t => <option key={t} value={t}>{BLOCK_LABEL[t]}</option>)}</select></label>
                <div className={styles.actions}>
                  <button type="button" className="button button-secondary" aria-label={`Chuyển khối ${bi + 1} của phần ${si + 1} lên`} disabled={bi === 0} onClick={() => mutate(b => ({ sections: replaceAt(b.sections, si, { ...section, blocks: moveItem(section.blocks, bi, bi - 1) }) }))}>↑</button>
                  <button type="button" className="button button-secondary" aria-label={`Chuyển khối ${bi + 1} của phần ${si + 1} xuống`} disabled={bi === section.blocks.length - 1} onClick={() => mutate(b => ({ sections: replaceAt(b.sections, si, { ...section, blocks: moveItem(section.blocks, bi, bi + 1) }) }))}>↓</button>
                  <button type="button" className="button button-secondary" aria-label={`Xóa khối ${bi + 1} của phần ${si + 1}`} onClick={() => mutate(b => ({ sections: replaceAt(b.sections, si, { ...section, blocks: removeAt(section.blocks, bi) }) }))}>Xóa</button>
                </div>
              </div>
              <label className={styles.field}><span>Nội dung khối {bi + 1} của phần {si + 1}</span>
                <textarea rows={4} value={block.text} maxLength={20000} onChange={e => mutate(b => ({ sections: replaceAt(b.sections, si, { ...section, blocks: replaceAt(section.blocks, bi, { ...block, text: e.target.value }) }) }))} /></label>
              {block.citations.length > 0 && <ul className={styles.chips} aria-label="Nguồn trích dẫn">{block.citations.map(c => <li key={c.chunkId}><Chip label={c.label || "Nguồn"} tone="info" /></li>)}</ul>}
            </div>)}
            <div className={styles.actions}>
              <button type="button" className="button button-secondary" disabled={section.blocks.length >= MAX_BLOCKS} onClick={() => mutate(b => ({ sections: replaceAt(b.sections, si, { ...section, blocks: [...section.blocks, newBlock()] }) }))}>Thêm khối</button>
              <button type="button" className="button button-secondary" aria-label={`Chuyển phần ${si + 1} lên`} disabled={si === 0} onClick={() => mutate(b => ({ sections: moveItem(b.sections, si, si - 1) }))}>Phần ↑</button>
              <button type="button" className="button button-secondary" aria-label={`Chuyển phần ${si + 1} xuống`} disabled={si === sectionCount - 1} onClick={() => mutate(b => ({ sections: moveItem(b.sections, si, si + 1) }))}>Phần ↓</button>
              <button type="button" className="button button-secondary" aria-label={`Xóa phần ${si + 1}`} disabled={sectionCount <= 1} onClick={() => mutate(b => ({ sections: removeAt(b.sections, si) }))}>Xóa phần</button>
            </div>
          </fieldset>)}
          <div><button type="button" className="button button-secondary" disabled={!editable || sectionCount >= MAX_SECTIONS} onClick={() => mutate(b => ({ sections: [...b.sections, newSection()] }))}>Thêm phần</button></div>
        </div>
        </div>}
        </div>
        {aiOpen && workspace && <AiDraftPanel wsBase={wsBase} csrf={csrf} itemId={itemId} kind={item.kind} unitId={item.curriculumUnitId} beforeStart={flush} onError={handle}
          onDone={async () => { await load(); setTab("content"); }} />}
        </div>

        <h2>Lịch sử phiên bản</h2>
        <div className={styles.tableWrap}><table className={styles.table}>
          <caption className="sr-only">Các phiên bản của nội dung</caption>
          <thead><tr><th scope="col">Bản</th><th scope="col">Trạng thái</th><th scope="col">Cập nhật</th><th scope="col"><span className="sr-only">Thao tác</span></th></tr></thead>
          <tbody>{revisions.slice().sort((a, b) => b.revisionNo - a.revisionNo).map(r => <tr key={r.revisionNo} data-active={r.revisionNo === rev.revisionNo}>
            <td>{r.revisionNo}</td><td><Chip label={REV_STATUS[r.status][0]} tone={REV_STATUS[r.status][1]} /></td><td>{dateTime(r.updatedAt)}</td>
            <td><button className="button button-secondary" onClick={() => void view(r.revisionNo)} aria-label={`Xem bản ${r.revisionNo}`}>Xem</button></td>
          </tr>)}</tbody>
        </table></div>
        {published && <>
          <h2>Xuất tệp</h2>
          <p className={styles.muted}>Bản {published.revisionNo} đã xuất bản, xuất sang DOCX.</p>
          <ExportControls wsBase={wsBase} csrf={csrf} target={{ contentRevisionId: published.id }} title={item.title} combos={[{ format: "docx", audience: "teacher" }, { format: "docx", audience: "student" }]} onError={handle} />
        </>}
      </>}
    </section>
    {source && source.chunkId && <CitationDrawer base={wsBase} chunkId={source.chunkId} title={source.label} onClose={() => setSource(null)} onError={handle} />}
    {viewing && <Modal title={`Bản ${viewing.revisionNo} (chỉ xem)`} onClose={() => setViewing(null)}>
      <div className={styles.preview}>{normalizeBody(viewing.body).sections.map((s, i) => <div key={i}><h3>{s.heading || `Phần ${i + 1}`}</h3>{s.blocks.map((b, j) => <p key={j}><strong>{BLOCK_LABEL[b.type]}: </strong>{b.text}</p>)}</div>)}</div>
      <div className={styles.actions}><button className="button button-secondary" onClick={() => setViewing(null)}>Đóng</button></div>
    </Modal>}
  </div></div>;
}
