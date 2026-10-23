"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@/lib/api/generated";
import { read } from "@/lib/client/api";
import { isActive, nextDelay } from "@/lib/client/jobs";
import { citationLabel, isPilotDraft, mergeById, sortUnits } from "@/lib/client/library";
import type { EmbeddingRun, EmbeddingRunList } from "@/lib/client/retrieval-types";
import { Modal } from "./modal";
import { TeachingNav } from "./teaching-nav";
import { useTeaching } from "./use-teaching";
import styles from "./teaching.module.css";

type Doc = components["schemas"]["DocumentDTO"];
type Job = components["schemas"]["JobDTO"];
type Version = components["schemas"]["DocumentVersionDTO"];
type Chunk = components["schemas"]["DocumentChunkDTO"];
type Unit = components["schemas"]["CurriculumUnitDTO"];
type Subject = components["schemas"]["CurriculumSubjectDTO"];

const DOC_STATUS: Record<Doc["status"], [string, string | undefined]> = { pending: ["Đang xử lý", "info"], uploaded: ["Sẵn sàng", undefined], quarantined: ["Bị cách ly", "error"], deleted: ["Đã xóa", "warn"] };
const VERSION_STATUS: Record<Version["status"], [string, string | undefined]> = { processing: ["Đang xử lý", "info"], active: ["Đang dùng", undefined], failed: ["Thất bại", "error"], superseded: ["Đã thay thế", "warn"] };
const JOB_LABEL: Record<Job["status"], string> = { queued: "Đang chờ xử lý", running: "Đang xử lý", succeeded: "Hoàn tất", failed: "Xử lý thất bại", cancelled: "Đã hủy" };
const RUN_STATUS: Record<string, [string, string | undefined]> = { queued: ["Đang chờ", "info"], running: ["Đang chạy", "info"], succeeded: ["Hoàn tất", undefined], failed: ["Thất bại", "error"], cancelled: ["Đã hủy", "warn"] };
const GRADES = Array.from({ length: 12 }, (_, i) => i + 1);
const size = (bytes: number) => bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(bytes / 1024)) + " KB";
const date = (value: string | null) => value ? new Date(value).toLocaleString("vi-VN") : "—";

export function LibraryDetailScreen({ documentId }: { documentId: string }) {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const [doc, setDoc] = useState<Doc | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null);
  const [runs, setRuns] = useState<EmbeddingRun[]>([]);
  const [chunkVersion, setChunkVersion] = useState("");
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [chunkCursor, setChunkCursor] = useState<string | null>(null);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [job, setJob] = useState<{ id: string; kind: "reingest" | "embed" | "delete"; status: Job["status"] } | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loadingDoc, setLoadingDoc] = useState(true);
  const [confirm, setConfirm] = useState(false);
  const [copied, setCopied] = useState("");
  const base = workspace ? `/api/backend/workspaces/${workspace.id}` : "";
  const docBase = base ? `${base}/documents/${documentId}` : "";
  const chunkEpoch = useRef(0);

  const refresh = useCallback(async () => {
    if (!docBase) return;
    try {
      const [d, v, r]: [Doc, { items: Version[]; activeVersionId: string | null }, EmbeddingRunList | null] = await Promise.all([
        read(docBase), read(`${docBase}/versions`),
        read(`${docBase}/embedding-runs`).catch((e: unknown) => { if (e && typeof e === "object" && "status" in e && (e as { status: number }).status === 404) return null; throw e; }),
      ]);
      setDoc(d); setVersions(v.items); setActiveVersionId(v.activeVersionId); setRuns(r ? r.items : []);
      setChunkVersion(current => current && v.items.some(x => x.id === current) ? current : v.activeVersionId || "");
      setError("");
    } catch (e) { setError(handle(e)); }
    finally { setLoadingDoc(false); }
  }, [docBase, handle]);
  // Network synchronization on workspace change.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void refresh(); }, [refresh]);

  // Chunk browser: reload from the first page whenever the selected version changes.
  const loadChunks = useCallback(async (versionId: string, after: string | null) => {
    if (!docBase || !versionId) { setChunks([]); setChunkCursor(null); return; }
    const epoch = ++chunkEpoch.current;
    setChunksLoading(true);
    try {
      const page: { items: Chunk[]; nextCursor: string | null } = await read(`${docBase}/versions/${versionId}/chunks?limit=20${after ? "&cursor=" + encodeURIComponent(after) : ""}`);
      if (epoch !== chunkEpoch.current) return;
      setChunks(current => after ? mergeById(current, page.items) : page.items);
      setChunkCursor(page.nextCursor);
    } catch (e) { if (epoch === chunkEpoch.current) setError(handle(e)); }
    finally { if (epoch === chunkEpoch.current) setChunksLoading(false); }
  }, [docBase, handle]);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void loadChunks(chunkVersion, null); }, [chunkVersion, loadChunks]);

  // Job polling: only while a tracked job is queued/running.
  const jobId = job && isActive(job.status) ? job.id : "";
  useEffect(() => {
    if (!jobId || !base) return;
    let stopped = false;
    let errors = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const next: Job = await read(`${base}/jobs/${jobId}`);
        if (stopped) return;
        errors = 0;
        if (!isActive(next.status)) {
          setJob(current => current && current.id === jobId ? { ...current, status: next.status } : current);
          await refresh();
          return;
        }
        setJob(current => current && current.id === jobId ? { ...current, status: next.status } : current);
      } catch (e) { if (stopped) return; errors++; handle(e); }
      if (!stopped) timer = setTimeout(() => void tick(), nextDelay(errors));
    };
    timer = setTimeout(() => void tick(), nextDelay(0));
    return () => { stopped = true; if (timer) clearTimeout(timer); };
  }, [jobId, base, handle, refresh]);

  async function start(kind: "reingest" | "embed") {
    setError(""); setNotice("");
    try {
      const result: { job: Job } = await read(`${docBase}/${kind}`, { method: "POST", headers: { "X-CSRF-Token": csrf } });
      setJob({ id: result.job.id, kind, status: result.job.status });
      setNotice(kind === "reingest" ? "Đã yêu cầu xử lý lại tài liệu." : "Đã yêu cầu tạo lại embedding.");
    } catch (e) { setError(handle(e)); }
  }
  async function remove() {
    setConfirm(false); setError(""); setNotice("");
    try {
      const result: { document: Doc; job: Job } = await read(docBase, { method: "DELETE", headers: { "X-CSRF-Token": csrf } });
      setDoc(result.document);
      setJob({ id: result.job.id, kind: "delete", status: result.job.status });
      setNotice("Đã xóa tài liệu. Các đoạn văn bản sẽ được dọn bằng một tác vụ nền.");
    } catch (e) { setError(handle(e)); }
  }
  async function copy(label: string, id: string) {
    try { await navigator.clipboard.writeText(label); setCopied(id); setTimeout(() => setCopied(""), 2000); }
    catch { setError("Không thể sao chép. Vui lòng sao chép thủ công."); }
  }

  const busy = job !== null && isActive(job.status);
  const deleted = doc?.status === "deleted";
  const [docLabel, docTone] = doc ? DOC_STATUS[doc.status] : ["", undefined];

  return <div className={styles.page}><div className={styles.wrap}>
    <TeachingNav current="library" />
    <Link className={styles.back} href="/dashboard/library">← Quay lại Thư viện</Link>
    <section className={styles.card} aria-busy={phase === "loading" || loadingDoc}>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {phase === "ready" && loadingDoc && <p role="status">Đang tải tài liệu…</p>}
      {doc && <>
        <div className={styles.head}><h1>{doc.fileName}</h1><span className={styles.chip} data-tone={docTone}>{docLabel}</span></div>
        <p className={styles.muted}>{doc.mimeType} · {size(doc.sizeBytes)} · Tải lên {date(doc.createdAt)}{doc.deletedAt ? " · Xóa " + date(doc.deletedAt) : ""}</p>
        <div className={styles.actions}>
          <button className="button button-secondary" disabled={busy || deleted} onClick={() => void start("reingest")}>Xử lý lại</button>
          <button className="button button-secondary" disabled={busy || deleted} onClick={() => void start("embed")}>Tạo lại embedding</button>
          <button className="button button-secondary" disabled={busy || deleted} onClick={() => setConfirm(true)}>Xóa tài liệu</button>
        </div>
        {job && <p role="status" aria-live="polite">{job.kind === "delete" ? "Xóa" : job.kind === "reingest" ? "Xử lý lại" : "Tạo embedding"}: {JOB_LABEL[job.status]}</p>}
      </>}
      {notice && <p role="status" aria-live="polite">{notice}</p>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
    </section>

    {doc && <section className={styles.card} aria-labelledby="versions-title">
      <h2 id="versions-title">Phiên bản</h2>
      {versions.length === 0 ? <p className={styles.muted}>Chưa có phiên bản nào.</p> : <div className={styles.tableWrap}><table className={styles.table}>
        <caption className="sr-only">Các phiên bản đã xử lý của tài liệu</caption>
        <thead><tr><th scope="col">Phiên bản</th><th scope="col">Trạng thái</th><th scope="col">Trang</th><th scope="col">Đoạn</th><th scope="col">Trình phân tích</th><th scope="col">Tạo lúc</th></tr></thead>
        <tbody>{versions.map(v => {
          const [label, tone] = VERSION_STATUS[v.status];
          return <tr key={v.id} data-active={v.id === activeVersionId}>
            <th scope="row">v{v.versionNo}{v.id === activeVersionId ? " (đang dùng)" : ""}</th>
            <td><span className={styles.chip} data-tone={tone}>{label}</span>{v.status === "failed" && <div className={styles.error}>{v.errorMessage || v.errorCode || "Xử lý thất bại."}</div>}</td>
            <td>{v.pageCount ?? "—"}</td><td>{v.chunkCount}</td><td>{v.parser} {v.parserVersion}</td><td>{date(v.createdAt)}</td>
          </tr>;
        })}</tbody></table></div>}
    </section>}

    {doc && <section className={styles.card} aria-labelledby="runs-title">
      <h2 id="runs-title">Lần tạo embedding</h2>
      {runs.length === 0 ? <p className={styles.muted}>Chưa có lần tạo embedding nào.</p> : <div className={styles.tableWrap}><table className={styles.table}>
        <caption className="sr-only">Các lần tạo embedding</caption>
        <thead><tr><th scope="col">Mô hình</th><th scope="col">Trạng thái</th><th scope="col">Đoạn</th><th scope="col">Tạo lúc</th><th scope="col">Kết thúc</th></tr></thead>
        <tbody>{runs.map(run => {
          const [label, tone] = RUN_STATUS[run.status] || [run.status, undefined];
          return <tr key={run.id}><th scope="row">{run.model} {run.version}</th>
            <td><span className={styles.chip} data-tone={tone}>{label}</span>{run.errorCode && <div className={styles.error}>{run.errorCode}</div>}</td>
            <td>{run.chunkCount ?? "—"}</td><td>{date(run.createdAt)}</td><td>{date(run.finishedAt)}</td></tr>;
        })}</tbody></table></div>}
    </section>}

    {doc && <section className={styles.card} aria-labelledby="chunks-title" aria-busy={chunksLoading}>
      <h2 id="chunks-title">Các đoạn văn bản</h2>
      {versions.length > 0 && <label className={styles.field}><span>Phiên bản</span>
        <select value={chunkVersion} onChange={e => setChunkVersion(e.target.value)}>
          {versions.map(v => <option key={v.id} value={v.id}>v{v.versionNo}{v.id === activeVersionId ? " (đang dùng)" : ""}</option>)}
        </select></label>}
      {!chunksLoading && chunks.length === 0 && <p className={styles.muted}>Chưa có đoạn văn bản nào.</p>}
      <ul className={styles.list}>{chunks.map(chunk => {
        const label = citationLabel({ pageNo: chunk.pageNo, sectionPath: chunk.sectionPath }, doc.fileName);
        return <li key={chunk.id} className={styles.chunk}>
          <div className={styles.head}><strong>Đoạn {chunk.chunkIndex + 1}</strong>
            <button className="button button-secondary" onClick={() => void copy(label, chunk.id)} aria-label={`Sao chép trích dẫn đoạn ${chunk.chunkIndex + 1}`}>{copied === chunk.id ? "Đã sao chép" : "Sao chép trích dẫn"}</button></div>
          <small className={styles.muted}>{label} · ~{chunk.tokenEstimate} token</small>
          <pre className={styles.mono}>{chunk.text}</pre>
        </li>;
      })}</ul>
      {chunkCursor && <button className="button button-secondary" disabled={chunksLoading} onClick={() => void loadChunks(chunkVersion, chunkCursor)}>Tải thêm</button>}
    </section>}

    {doc && !deleted && <TagsEditor docBase={docBase} csrf={csrf} handle={handle} />}

    {confirm && doc && <Modal title="Xóa tài liệu?" onClose={() => setConfirm(false)}>
      <p>Tài liệu “{doc.fileName}” sẽ bị xóa mềm khỏi workspace. Các đoạn văn bản và embedding sẽ được dọn bằng một tác vụ nền, nên có thể mất ít phút.</p>
      <div className={styles.actions}><button className="button button-primary" onClick={() => void remove()}>Xóa</button><button className="button button-secondary" onClick={() => setConfirm(false)}>Hủy</button></div>
    </Modal>}
  </div></div>;
}

function TagsEditor({ docBase, csrf, handle }: { docBase: string; csrf: string; handle: (e: unknown) => string }) {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [subject, setSubject] = useState("");
  const [grade, setGrade] = useState("");
  const [units, setUnits] = useState<Unit[]>([]);
  const [selected, setSelected] = useState<Record<string, Unit>>({});
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let live = true;
    Promise.all([read(`${docBase}/curriculum-tags`), read("/api/backend/curriculum/subjects")]).then(([tags, subs]: [{ items: Unit[] }, { items: Subject[] }]) => {
      if (!live) return;
      setSelected(Object.fromEntries(tags.items.map(u => [u.id, u])));
      setSubjects(subs.items); setLoaded(true);
    }, (e: unknown) => { if (live) setError(handle(e)); });
    return () => { live = false; };
  }, [docBase, handle]);
  useEffect(() => {
    if (!subject || !grade) return;
    let live = true;
    read(`/api/backend/curriculum/units?subject=${encodeURIComponent(subject)}&grade=${encodeURIComponent(grade)}`).then(
      (res: { items: Unit[] }) => { if (live) setUnits(sortUnits(res.items)); },
      (e: unknown) => { if (live) setError(handle(e)); });
    return () => { live = false; };
  }, [subject, grade, handle]);

  const shown = subject && grade ? units : [];
  const toggle = (unit: Unit) => { setNotice(""); setSelected(current => { const next = { ...current }; if (next[unit.id]) delete next[unit.id]; else next[unit.id] = unit; return next; }); };
  async function save() {
    setSaving(true); setError(""); setNotice("");
    try {
      const res: { items: Unit[] } = await read(`${docBase}/curriculum-tags`, { method: "PUT", headers: { "X-CSRF-Token": csrf, "Content-Type": "application/json" }, body: JSON.stringify({ unitIds: Object.keys(selected) }) });
      setSelected(Object.fromEntries(res.items.map(u => [u.id, u])));
      setNotice("Đã lưu thẻ chương trình.");
    } catch (e) { setError(handle(e)); }
    finally { setSaving(false); }
  }
  const chosen = Object.values(selected);
  return <section className={styles.card} aria-labelledby="tags-title" aria-busy={!loaded || saving}>
    <h2 id="tags-title">Thẻ chương trình học</h2>
    <div className={styles.tagGrid}>
      <label className={styles.field}><span>Môn học</span>
        <select value={subject} onChange={e => { setSubject(e.target.value); setGrade(""); setUnits([]); }} disabled={!loaded}>
          <option value="">Chọn môn học</option>{subjects.map(s => <option key={s.id} value={s.code}>{s.nameVi}</option>)}
        </select></label>
      <label className={styles.field}><span>Khối lớp</span>
        <select value={grade} onChange={e => setGrade(e.target.value)} disabled={!subject}>
          <option value="">Chọn khối lớp</option>{GRADES.map(g => <option key={g} value={g}>Lớp {g}</option>)}
        </select></label>
    </div>
    {subject && grade && shown.length === 0 && <p className={styles.muted}>Không có đơn vị kiến thức cho lựa chọn này.</p>}
    {shown.length > 0 && <fieldset className={styles.docFilter}><legend>Đơn vị kiến thức</legend><ul className={styles.unitList}>
      {shown.map(unit => <li key={unit.id}><label className={styles.check}><input type="checkbox" checked={Boolean(selected[unit.id])} onChange={() => toggle(unit)} /><span>{unit.unitCode} · {unit.titleVi}{isPilotDraft(unit.sourceProvenance) && <small className={styles.muted}> (bản nháp thí điểm)</small>}</span></label></li>)}
    </ul></fieldset>}
    <div>
      <strong>Đã gắn ({chosen.length})</strong>
      {chosen.length === 0 ? <p className={styles.muted}>Chưa gắn thẻ nào.</p> : <ul className={styles.unitList}>{chosen.map(unit => <li key={unit.id} className={styles.muted}>Lớp {unit.grade} · {unit.unitCode} · {unit.titleVi}</li>)}</ul>}
    </div>
    {chosen.some(u => isPilotDraft(u.sourceProvenance)) && <p className={styles.muted}>Nguồn dữ liệu chương trình: seed:pilot-draft (bản nháp thí điểm, chưa chính thức).</p>}
    <div className={styles.actions}><button className="button button-primary" disabled={saving || !loaded} onClick={() => void save()}>{saving ? "Đang lưu…" : "Lưu thẻ"}</button></div>
    {notice && <p role="status" aria-live="polite">{notice}</p>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </section>;
}
