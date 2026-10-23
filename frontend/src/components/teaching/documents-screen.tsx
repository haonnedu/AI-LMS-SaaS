"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import type { components } from "@/lib/api/generated";
import { read, RequestError } from "@/lib/client/api";
import { isActive, nextDelay } from "@/lib/client/jobs";
import { buildUploadHeaders, UPLOAD_ACCEPT, uploadContentType } from "@/lib/client/upload";
import { Modal } from "./modal";
import { TeachingNav } from "./teaching-nav";
import { useTeaching } from "./use-teaching";
import styles from "./teaching.module.css";

type Doc = components["schemas"]["DocumentDTO"];
type Job = components["schemas"]["JobDTO"];
const DOC_STATUS: Record<Doc["status"], [string, string | undefined]> = { pending: ["Đang xử lý", "info"], uploaded: ["Sẵn sàng", undefined], quarantined: ["Bị cách ly", "error"], deleted: ["Đã xóa", "warn"] };
const JOB_STATUS: Record<Job["status"], [string, string | undefined]> = { queued: ["Đang chờ xử lý", "info"], running: ["Đang xử lý", "info"], succeeded: ["Hoàn tất", undefined], failed: ["Xử lý thất bại", "error"], cancelled: ["Đã hủy", "warn"] };
const UPLOAD_ERRORS: Record<string, string> = {
  file_too_large: "Tệp quá lớn. Vui lòng chọn tệp nhỏ hơn.",
  unsupported_media_type: "Chỉ hỗ trợ tệp PDF, DOCX hoặc TXT.",
  rights_attestation_required: "Bạn cần xác nhận quyền sử dụng tài liệu.",
  quota_exceeded: "Đã hết hạn mức lưu trữ hoặc tải lên của workspace.",
};
const size = (bytes: number) => bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(bytes / 1024)) + " KB";

export function DocumentsScreen() {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Record<string, string>>({}); // documentId -> jobId
  const [jobStatus, setJobStatus] = useState<Record<string, Job["status"]>>({}); // jobId -> status
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [attested, setAttested] = useState(false);
  const [fileError, setFileError] = useState("");
  const [confirm, setConfirm] = useState<Doc | null>(null);
  const idempotency = useRef("");
  const input = useRef<HTMLInputElement>(null);
  const epoch = useRef(0);
  const invalidate = useCallback(() => { epoch.current++; }, []);
  const base = workspace ? `/api/backend/workspaces/${workspace.id}` : "";

  const fetchPage = useCallback(async (after: string | null) => {
    if (!base) return;
    const version = ++epoch.current;
    setLoading(true); setError("");
    try {
      const result = await read(`${base}/documents?limit=20${after ? "&cursor=" + encodeURIComponent(after) : ""}`);
      if (version !== epoch.current) return;
      setDocs(current => after ? [...current, ...result.items] : result.items);
      setCursor(result.nextCursor);
    } catch (e) { if (version === epoch.current) setError(handle(e)); }
    finally { if (version === epoch.current) setLoading(false); }
  }, [base, handle]);
  // Network synchronization on workspace change.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void fetchPage(null); return invalidate; }, [fetchPage, invalidate]);

  // Polling: runs only while a tracked job is queued/running or a document is pending; stops on terminal state/unmount.
  const latest = useRef({ docs, jobs, jobStatus });
  useEffect(() => { latest.current = { docs, jobs, jobStatus }; });
  const needsPoll = docs.some(d => d.status === "pending") || Object.values(jobStatus).some(isActive);
  useEffect(() => {
    if (!needsPoll || !base) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let errors = 0;
    const tick = async () => {
      const { docs: currentDocs, jobs: tracked, jobStatus: statuses } = latest.current;
      let changed = false;
      let failed = false;
      const active = Object.values(tracked).filter(id => isActive(statuses[id] || "queued"));
      const untrackedPending = currentDocs.some(d => d.status === "pending" && !tracked[d.id]);
      const results = await Promise.all(active.map(async id => {
        try { const job: Job = await read(`${base}/jobs/${id}`); return { id, status: job.status }; }
        catch (e) { if (e instanceof RequestError && e.status === 401) handle(e); return { id, status: undefined }; }
      }));
      if (stopped) return;
      const updates: Record<string, Job["status"]> = {};
      for (const result of results) {
        if (!result.status) { failed = true; continue; }
        if (statuses[result.id] !== result.status) { updates[result.id] = result.status; changed = true; }
      }
      if (changed) setJobStatus(current => ({ ...current, ...updates }));
      if (changed || untrackedPending) {
        try {
          const fresh = await read(`${base}/documents?limit=20`);
          if (stopped) return;
          setDocs(fresh.items); setCursor(fresh.nextCursor);
        } catch { failed = true; }
      }
      errors = failed ? errors + 1 : 0;
      if (!stopped) timer = setTimeout(() => void tick(), nextDelay(errors));
    };
    timer = setTimeout(() => void tick(), nextDelay(0));
    return () => { stopped = true; if (timer) clearTimeout(timer); };
  }, [needsPoll, base, handle]);

  function pick(event: ChangeEvent<HTMLInputElement>) {
    const chosen = event.target.files?.[0] || null;
    setNotice(""); setError("");
    if (chosen && !uploadContentType(chosen.name)) { setFile(null); setFileError("Chỉ hỗ trợ tệp PDF, DOCX hoặc TXT."); event.target.value = ""; return; }
    setFileError(""); setFile(chosen); idempotency.current = chosen ? crypto.randomUUID() : "";
  }
  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file || !attested || uploading || !base) return;
    const headers = buildUploadHeaders(file, csrf, idempotency.current);
    if (!headers) { setFileError("Chỉ hỗ trợ tệp PDF, DOCX hoặc TXT."); return; }
    setUploading(true); setError(""); setNotice("");
    try {
      const result: { document: Doc; job: Job } = await read(`${base}/documents`, { method: "POST", headers, body: file }, 120000);
      setJobs(current => ({ ...current, [result.document.id]: result.job.id }));
      setJobStatus(current => ({ ...current, [result.job.id]: result.job.status }));
      setDocs(current => [result.document, ...current.filter(d => d.id !== result.document.id)]);
      setNotice("Đã tải lên. Tài liệu đang được xử lý.");
      setFile(null); setAttested(false); idempotency.current = "";
      if (input.current) input.current.value = "";
    } catch (e) { setError(e instanceof RequestError && UPLOAD_ERRORS[e.code] ? UPLOAD_ERRORS[e.code] : handle(e)); }
    finally { setUploading(false); }
  }
  async function download(doc: Doc) {
    setError(""); setNotice("");
    try {
      const result: { url: string } = await read(`${base}/documents/${doc.id}/download`);
      const url = new URL(result.url);
      if (!["https:", "http:"].includes(url.protocol)) throw new Error("bad_url");
      const link = document.createElement("a");
      link.href = url.toString(); link.target = "_blank"; link.rel = "noopener noreferrer";
      document.body.appendChild(link); link.click(); link.remove();
    } catch (e) { setError(e instanceof RequestError ? handle(e) : "Không thể tạo liên kết tải xuống. Vui lòng thử lại."); }
  }
  async function remove(doc: Doc) {
    setConfirm(null); setError(""); setNotice("");
    try {
      const result: { document: Doc; job: Job } = await read(`${base}/documents/${doc.id}`, { method: "DELETE", headers: { "X-CSRF-Token": csrf } });
      setJobs(current => ({ ...current, [doc.id]: result.job.id }));
      setJobStatus(current => ({ ...current, [result.job.id]: result.job.status }));
      setDocs(current => current.map(d => d.id === doc.id ? result.document : d));
      setNotice("Đang xóa tài liệu.");
    } catch (e) { setError(handle(e)); }
  }

  return <div className={styles.page}><div className={styles.wrap}>
    <TeachingNav current="documents" />
    <section className={styles.card} aria-busy={uploading || phase === "loading"}>
      <div className={styles.head}><h1>Tài liệu</h1>{workspace && <span className={styles.muted}>{workspace.name}</span>}</div>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {phase === "ready" && <form onSubmit={event => void upload(event)} className={styles.form} aria-label="Tải tài liệu lên">
        <label className={styles.field}><span>Chọn tệp (PDF, DOCX hoặc TXT)</span><input ref={input} type="file" accept={UPLOAD_ACCEPT} onChange={pick} disabled={uploading} aria-describedby={fileError ? "file-error" : undefined} /></label>
        <label className={styles.check}><input type="checkbox" checked={attested} onChange={e => setAttested(e.target.checked)} disabled={uploading} /><span>Tôi xác nhận có quyền sử dụng tài liệu này</span></label>
        <button className="button button-primary" type="submit" disabled={!file || !attested || uploading}>{uploading ? "Đang tải lên…" : "Tải lên"}</button>
        {file && <p className={styles.muted}>{file.name} · {size(file.size)}</p>}
        {fileError && <p id="file-error" role="alert" className={styles.error}>{fileError}</p>}
      </form>}
      {notice && <p role="status" aria-live="polite">{notice}</p>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
    </section>
    {phase === "ready" && <section className={styles.card} aria-busy={loading} aria-label="Danh sách tài liệu">
      <h2>Tài liệu của bạn</h2>
      {loading && docs.length === 0 && <p role="status">Đang tải danh sách…</p>}
      {!loading && docs.length === 0 && <p className={styles.muted}>Chưa có tài liệu nào. Hãy tải lên tệp đầu tiên.</p>}
      <ul className={styles.list}>{docs.map(doc => {
        const jobId = jobs[doc.id];
        const state = jobId ? jobStatus[jobId] : undefined;
        const [label, tone] = doc.status === "pending" && state && state !== "succeeded" ? JOB_STATUS[state] : DOC_STATUS[doc.status];
        return <li key={doc.id} className={styles.item}>
          <div><strong>{doc.fileName}</strong><small>{size(doc.sizeBytes)} · {new Date(doc.createdAt).toLocaleDateString("vi-VN")}</small></div>
          <span className={styles.chip} data-tone={tone}>{label}</span>
          <div className={styles.actions}>
            {doc.status === "uploaded" && <Link className="button button-secondary" href={`/dashboard/library/${doc.id}`} aria-label={`Chi tiết ${doc.fileName}`}>Chi tiết</Link>}
            <button className="button button-secondary" disabled={doc.status !== "uploaded"} onClick={() => void download(doc)} aria-label={`Tải xuống ${doc.fileName}`}>Tải xuống</button>
            <button className="button button-secondary" disabled={doc.status === "deleted"} onClick={() => setConfirm(doc)} aria-label={`Xóa ${doc.fileName}`}>Xóa</button>
          </div></li>;
      })}</ul>
      {cursor && <button className="button button-secondary" disabled={loading} onClick={() => void fetchPage(cursor)}>Tải thêm</button>}
    </section>}
    {confirm && <Modal title="Xóa tài liệu?" onClose={() => setConfirm(null)}>
      <p>Tài liệu “{confirm.fileName}” sẽ bị xóa khỏi workspace.</p>
      <div className={styles.actions}><button className="button button-primary" onClick={() => void remove(confirm)}>Xóa</button><button className="button button-secondary" onClick={() => setConfirm(null)}>Hủy</button></div>
    </Modal>}
  </div></div>;
}
