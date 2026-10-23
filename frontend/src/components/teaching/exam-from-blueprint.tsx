"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { jsonInit, read, RequestError } from "@/lib/client/api";
import { COGNITIVE_LABEL } from "@/lib/client/authoring";
import { AI_UNAVAILABLE_MESSAGE, buildExamFromBlueprint, isAiUnavailableCode, reportFromError, suggestionsToRequests, type SelectionReportLike } from "@/lib/client/generation";
import { unitLabel } from "./authoring-shared";
import { Modal } from "./modal";
import styles from "./teaching.module.css";

type Progress = { done: number; total: number; failed: number; unavailable: boolean };

/** "Tạo đề từ ma trận": builds an exam from a published blueprint version; shows missing slots on insufficient_pool. */
export function ExamFromBlueprint({ wsBase, csrf, versionId, grade, subject, onError }: { wsBase: string; csrf: string; versionId: string | null; grade: number; subject: string; onError: (e: unknown) => string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [seed, setSeed] = useState("");
  const [title, setTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<SelectionReportLike | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);

  function close() { setOpen(false); setError(""); setReport(null); setProgress(null); }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!versionId) return;
    const built = buildExamFromBlueprint(versionId, seed, title);
    if (!built.ok) { setError(built.message); return; }
    setSaving(true); setError(""); setReport(null); setProgress(null);
    try {
      const created: { id: string } = await read(`${wsBase}/exams`, jsonInit(csrf, built.value), 30000);
      router.push(`/dashboard/exams/${created.id}`);
    } catch (e) {
      const found = e instanceof RequestError && e.code === "insufficient_pool" ? reportFromError(e.detail) : null;
      if (found) { setReport(found); setError("Ngân hàng câu hỏi chưa đủ để dựng đề theo ma trận này."); }
      else setError(onError(e));
      setSaving(false);
    }
  }
  async function generate() {
    if (!report) return;
    const requests = suggestionsToRequests(report, { grade, subject });
    if (requests.length === 0) return;
    setProgress({ done: 0, total: requests.length, failed: 0, unavailable: false });
    let failed = 0, done = 0, unavailable = false;
    for (const request of requests) {
      try { await read(`${wsBase}/generation/drafts`, jsonInit(csrf, request), 30000); done++; }
      catch (e) {
        if (e instanceof RequestError && (e.status === 503 || isAiUnavailableCode(e.code))) { unavailable = true; break; }
        failed++; onError(e);
      }
      setProgress({ done, total: requests.length, failed, unavailable });
    }
    setProgress({ done, total: requests.length, failed, unavailable });
  }
  const canGenerate = !!report && report.suggestedGeneration.length > 0 && (!progress || progress.unavailable);

  return <>
    <button type="button" className="button button-primary" disabled={!versionId} onClick={() => setOpen(true)}>Tạo đề từ ma trận</button>
    {!versionId && <small className={styles.muted}>Cần xuất bản ma trận trước khi tạo đề.</small>}
    {open && <Modal title="Tạo đề từ ma trận" onClose={() => !saving && close()}>
      <form onSubmit={event => void submit(event)}>
        <label className={styles.field}><span>Tên đề (tùy chọn)</span><input value={title} maxLength={200} onChange={e => setTitle(e.target.value)} autoFocus /></label>
        <label className={styles.field}><span>Seed (tùy chọn, để lặp lại cùng một cách chọn câu)</span><input value={seed} maxLength={64} onChange={e => setSeed(e.target.value)} /></label>
        {error && <p role="alert" className={styles.error}>{error}</p>}
        {report && <div className={styles.dialogBody} aria-live="polite">
          <h3>Các ô còn thiếu câu hỏi</h3>
          <div className={styles.tableWrap}><table className={styles.table}>
            <caption className="sr-only">Các ô thiếu câu hỏi</caption>
            <thead><tr><th scope="col">Phần</th><th scope="col">Câu</th><th scope="col">Đơn vị kiến thức</th><th scope="col">Mức nhận thức</th><th scope="col">Độ khó</th><th scope="col">Lý do</th></tr></thead>
            <tbody>{report.missingSlots.map((slot, i) => <tr key={i}>
              <td>{slot.partCode}</td><td>{slot.index}</td><td>{unitLabel(slot.curriculumUnitId)}</td><td>{COGNITIVE_LABEL[slot.cognitiveLevel] || slot.cognitiveLevel}</td><td>{slot.difficulty ?? "—"}</td><td>{slot.reason}</td>
            </tr>)}</tbody>
          </table></div>
          {report.suggestedGeneration.length > 0 && <p className={styles.muted}>Gợi ý: {report.suggestedGeneration.map(s => `${s.count} câu ${COGNITIVE_LABEL[s.cognitiveLevel] || s.cognitiveLevel}`).join("; ")}.</p>}
          <div className={styles.actions}>
            <button type="button" className="button button-secondary" disabled={!canGenerate} onClick={() => void generate()}>Tạo câu hỏi bằng AI cho các ô thiếu</button>
          </div>
          {progress && <p role="status">
            {progress.unavailable ? AI_UNAVAILABLE_MESSAGE : `Đã gửi ${progress.done}/${progress.total} yêu cầu tạo câu hỏi${progress.failed ? `, ${progress.failed} yêu cầu lỗi` : ""}.`}{" "}
            {progress.done > 0 && <>Câu hỏi AI ở dạng nháp, hãy <Link href="/dashboard/questions?status=draft">xem và duyệt câu hỏi nháp</Link> rồi tạo lại đề.</>}
          </p>}
        </div>}
        <div className={styles.actions}>
          <button className="button button-primary" type="submit" disabled={saving}>{saving ? "Đang tạo…" : "Tạo đề"}</button>
          <button className="button button-secondary" type="button" disabled={saving} onClick={close}>Đóng</button>
        </div>
      </form>
    </Modal>}
  </>;
}
