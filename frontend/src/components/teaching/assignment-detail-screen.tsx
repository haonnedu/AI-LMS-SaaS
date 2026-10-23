"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { components } from "@/lib/api/generated";
import { jsonInit, read } from "@/lib/client/api";
import { ASSIGNMENT_STATUS, buildOverrideBody, denominatorsText, formatDuration, GRADING_LABEL, isoToZoned, scoreText, SCORE_RELEASE_LABEL, SOLUTION_RELEASE_LABEL, SUBMISSION_REASON, zonedToIso } from "@/lib/client/assessment";
import { Chip, dateTime } from "./authoring-shared";
import { Modal } from "./modal";
import { TeachingNav } from "./teaching-nav";
import { useTeaching } from "./use-teaching";
import styles from "./teaching.module.css";

type Assignment = components["schemas"]["AssignmentDTO"];
type Results = components["schemas"]["ResultsDTO"];
type ResultRow = Results["items"][number];
type Attempt = components["schemas"]["TeacherAttemptDTO"];
type ActionKey = "publish" | "close" | "archive" | "release-scores" | "release-solutions";
const ACTIONS: Record<ActionKey, { title: string; body: string; done: string; confirm: string }> = {
  publish: { title: "Xuất bản bài giao?", body: "Học sinh trong lớp sẽ thấy bài giao và có thể làm bài khi đến giờ mở. Đề và đáp án được chốt tại thời điểm này.", done: "Đã xuất bản bài giao.", confirm: "Xuất bản" },
  close: { title: "Đóng bài giao?", body: "Học sinh sẽ không thể bắt đầu hoặc tiếp tục làm bài. Các bài đang làm sẽ được nộp theo hạn.", done: "Đã đóng bài giao.", confirm: "Đóng bài" },
  archive: { title: "Lưu trữ bài giao?", body: "Bài giao sẽ được lưu trữ và không còn hiển thị cho học sinh.", done: "Đã lưu trữ bài giao.", confirm: "Lưu trữ" },
  "release-scores": { title: "Công bố điểm?", body: "Học sinh sẽ nhìn thấy điểm của mình. Chỉ các bài đã chấm được công bố.", done: "Đã công bố điểm.", confirm: "Công bố điểm" },
  "release-solutions": { title: "Công bố đáp án?", body: "Học sinh đã nộp bài sẽ xem được đáp án và giải thích. Hành động này không thể hoàn tác.", done: "Đã công bố đáp án.", confirm: "Công bố đáp án" },
};

export function AssignmentDetailScreen({ assignmentId }: { assignmentId: string }) {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [results, setResults] = useState<Results | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirm, setConfirm] = useState<ActionKey | null>(null);
  const [extending, setExtending] = useState(false);
  const [attemptRow, setAttemptRow] = useState<ResultRow | null>(null);
  const epoch = useRef(0);
  const base = workspace ? `/api/backend/workspaces/${workspace.id}/assignments/${assignmentId}` : "";

  const load = useCallback(async () => {
    if (!base) return;
    const mine = ++epoch.current;
    setLoading(true); setError("");
    try {
      const [detail, list] = await Promise.all([read(base), read(base + "/results")]);
      if (mine !== epoch.current) return;
      setAssignment(detail); setResults(list);
    } catch (e) { if (mine === epoch.current) setError(handle(e)); }
    finally { if (mine === epoch.current) setLoading(false); }
  }, [base, handle]);
  // Network synchronization once the workspace is known.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, [load]);

  async function run(action: ActionKey) {
    setConfirm(null); setBusy(true); setError(""); setNotice("");
    try { await read(`${base}/${action}`, jsonInit(csrf)); setNotice(ACTIONS[action].done); await load(); }
    catch (e) { setError(handle(e)); }
    finally { setBusy(false); }
  }
  async function exportCsv() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`${base}/results/export.csv`, { cache: "no-store", signal: AbortSignal.timeout(30000) });
      if (!response.ok) { const payload = await response.json().catch(() => null); throw new Error(payload?.error?.message || "Chưa thể xuất tệp. Vui lòng thử lại."); }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = "ket-qua-bai-giao.csv"; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(e instanceof Error ? e.message : "Chưa thể xuất tệp. Vui lòng thử lại."); }
    finally { setBusy(false); }
  }

  const status = assignment?.status;
  const can = {
    publish: status === "draft",
    close: status === "published",
    extend: status === "published" || status === "closed",
    archive: status === "draft" || status === "closed",
    scores: !!assignment && status !== "draft" && status !== "archived" && !assignment.scoresReleasedAt,
    solutions: !!assignment && status !== "draft" && status !== "archived" && assignment.solutionRelease !== "never" && !assignment.solutionsReleasedAt,
  };

  return <div className={styles.page}><div className={styles.wrap}>
    <TeachingNav current="classes" />
    {assignment && <Link href={`/dashboard/classes/${assignment.classId}/assignments`} className={styles.back}>← Bài giao của lớp</Link>}
    <section className={styles.card} aria-busy={loading || phase === "loading"}>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {assignment && <>
        <div className={styles.head}><div><h1>{assignment.title}</h1>
          <p className={styles.muted}>Mở {dateTime(assignment.opensAt)} · Đóng {assignment.closesAt ? dateTime(assignment.closesAt) : "không giới hạn"} · {assignment.timezone}</p></div>
          <Chip label={ASSIGNMENT_STATUS[assignment.status][0]} tone={ASSIGNMENT_STATUS[assignment.status][1]} /></div>
        <p className={styles.muted}>Thời gian làm bài: {formatDuration(assignment.timeLimitSeconds)} · Tối đa {assignment.maxAttempts} lần</p>
        <ul className={styles.chips} aria-label="Trạng thái công bố">
          <li><Chip label={assignment.scoresReleasedAt ? "Điểm đã công bố" : `Điểm: ${SCORE_RELEASE_LABEL[assignment.scoreRelease]}`} tone={assignment.scoresReleasedAt ? undefined : "warn"} /></li>
          <li><Chip label={assignment.solutionsReleasedAt ? "Đáp án đã công bố" : `Đáp án: ${SOLUTION_RELEASE_LABEL[assignment.solutionRelease]}`} tone={assignment.solutionsReleasedAt ? undefined : "warn"} /></li>
        </ul>
        {assignment.instructions && <p>{assignment.instructions}</p>}
        <div className={styles.actions}>
          {can.publish && <button className="button button-primary" disabled={busy} onClick={() => setConfirm("publish")}>Xuất bản</button>}
          {can.close && <button className="button button-secondary" disabled={busy} onClick={() => setConfirm("close")}>Đóng bài</button>}
          {can.extend && <button className="button button-secondary" disabled={busy} onClick={() => setExtending(true)}>Gia hạn</button>}
          {can.scores && <button className="button button-secondary" disabled={busy} onClick={() => setConfirm("release-scores")}>Công bố điểm</button>}
          {can.solutions && <button className="button button-secondary" disabled={busy} onClick={() => setConfirm("release-solutions")}>Công bố đáp án</button>}
          {can.archive && <button className="button button-secondary" disabled={busy} onClick={() => setConfirm("archive")}>Lưu trữ</button>}
        </div>
      </>}
      {notice && <p role="status" aria-live="polite" className={styles.notice}>{notice}</p>}
      {error && !extending && !attemptRow && <p role="alert" className={styles.error}>{error} <button className="button button-secondary" onClick={() => void load()}>Tải lại</button></p>}
    </section>
    {results && <section className={styles.card} aria-label="Kết quả">
      <div className={styles.head}><h2>Kết quả</h2><button className="button button-secondary" disabled={busy} onClick={() => void exportCsv()}>Xuất CSV</button></div>
      <p role="status" aria-live="polite"><strong>{denominatorsText(results.denominators)}</strong></p>
      {results.items.length === 0 ? <p className={styles.muted}>Chưa có học sinh trong lớp.</p> :
        <div className={styles.tableWrap}><table className={styles.table}>
          <caption className="sr-only">Kết quả của học sinh</caption>
          <thead><tr><th scope="col">Học sinh</th><th scope="col">Trạng thái</th><th scope="col">Lần</th><th scope="col">Điểm</th><th scope="col">Nộp lúc</th><th scope="col"><span className="sr-only">Chi tiết</span></th></tr></thead>
          <tbody>{results.items.map(row => {
            const grading = GRADING_LABEL[row.gradingStatus] || [row.gradingStatus, undefined];
            return <tr key={row.studentId}>
              <th scope="row">{row.displayName}</th>
              <td><Chip label={grading[0]} tone={grading[1]} /></td>
              <td>{row.attemptNo ?? "—"}</td>
              <td>{scoreText(row.score, row.maxScore)}</td>
              <td>{row.submittedAt ? dateTime(row.submittedAt) : "—"}</td>
              <td>{row.attemptId && <button className="button button-secondary" onClick={() => { setError(""); setAttemptRow(row); }} aria-label={`Xem bài làm của ${row.displayName}`}>Chi tiết</button>}</td>
            </tr>;
          })}</tbody>
        </table></div>}
    </section>}
    {confirm && <Modal title={ACTIONS[confirm].title} onClose={() => setConfirm(null)}>
      <p>{ACTIONS[confirm].body}</p>
      <div className={styles.actions}><button className="button button-primary" onClick={() => void run(confirm)}>{ACTIONS[confirm].confirm}</button><button className="button button-secondary" onClick={() => setConfirm(null)}>Hủy</button></div>
    </Modal>}
    {extending && assignment && <ExtendDialog assignment={assignment} base={base} csrf={csrf} handle={handle} onClose={() => setExtending(false)} onDone={() => { setExtending(false); setNotice("Đã gia hạn bài giao."); void load(); }} />}
    {attemptRow?.attemptId && <AttemptDialog base={base} attemptId={attemptRow.attemptId} csrf={csrf} handle={handle} onClose={() => setAttemptRow(null)} onChanged={() => void load()} />}
  </div></div>;
}

function ExtendDialog({ assignment, base, csrf, handle, onClose, onDone }: { assignment: Assignment; base: string; csrf: string; handle: (e: unknown) => string; onClose: () => void; onDone: () => void }) {
  const [value, setValue] = useState(assignment.closesAt ? isoToZoned(assignment.closesAt, assignment.timezone) : "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    const closesAt = zonedToIso(value, assignment.timezone);
    if (!closesAt) { setError("Hãy chọn thời điểm đóng mới."); return; }
    if (assignment.closesAt && Date.parse(closesAt) <= Date.parse(assignment.closesAt)) { setError("Thời điểm mới phải sau hạn hiện tại."); return; }
    setSaving(true); setError("");
    try { await read(base + "/extend", jsonInit(csrf, { closesAt })); onDone(); }
    catch (e) { setError(handle(e)); setSaving(false); }
  }
  return <Modal title="Gia hạn bài giao" onClose={onClose}>
    <form onSubmit={event => void submit(event)} noValidate>
      <p className={styles.muted}>Hạn hiện tại: {assignment.closesAt ? dateTime(assignment.closesAt) : "không giới hạn"} (múi giờ {assignment.timezone})</p>
      <label className={styles.field}><span>Đóng bài lúc *</span><input type="datetime-local" value={value} onChange={e => setValue(e.target.value)} required /></label>
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <div className={styles.actions}><button className="button button-primary" type="submit" disabled={saving}>Gia hạn</button><button type="button" className="button button-secondary" onClick={onClose}>Hủy</button></div>
    </form>
  </Modal>;
}

function AttemptDialog({ base, attemptId, csrf, handle, onClose, onChanged }: { base: string; attemptId: string; csrf: string; handle: (e: unknown) => string; onClose: () => void; onChanged: () => void }) {
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [score, setScore] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const url = `${base}/attempts/${attemptId}`;
  const load = useCallback(async () => {
    try { setAttempt(await read(url)); setError(""); } catch (e) { setError(handle(e)); }
  }, [url, handle]);
  // Network synchronization when the dialog opens.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, [load]);

  const current = attempt?.grades.find(g => g.isCurrent) || null;
  async function override(event: FormEvent) {
    event.preventDefault();
    const built = buildOverrideBody(score, reason, current?.maxScore ?? attempt?.items.reduce((sum, item) => sum + Number(item.points), 0) ?? null);
    if (!built.ok) { setError(built.error); return; }
    setSaving(true); setError(""); setNotice("");
    try {
      await read(`${url}/override`, jsonInit(csrf, built.body));
      setNotice("Đã điều chỉnh điểm."); setScore(""); setReason("");
      await load(); onChanged();
    } catch (e) { setError(handle(e)); }
    finally { setSaving(false); }
  }
  return <Modal title={attempt ? `Bài làm của ${attempt.displayName}` : "Bài làm"} onClose={onClose}>
    <div className={styles.dialogBody}>
      {!attempt && !error && <p role="status">Đang tải…</p>}
      {attempt && <>
        <p className={styles.muted}>Lần {attempt.attemptNo} · {GRADING_LABEL[attempt.gradingStatus]?.[0] || attempt.gradingStatus}
          {attempt.submittedAt ? ` · Nộp ${dateTime(attempt.submittedAt)}` : ""}{attempt.submissionReason ? ` (${SUBMISSION_REASON[attempt.submissionReason]})` : ""}</p>
        <p><strong>Điểm hiện tại: {current ? scoreText(current.score, current.maxScore) : "Chờ chấm"}</strong></p>
        <div className={styles.tableWrap}><table className={styles.table}>
          <caption className="sr-only">Chi tiết từng câu</caption>
          <thead><tr><th scope="col">Câu</th><th scope="col">Đã chọn</th><th scope="col">Đáp án đúng</th><th scope="col">Điểm</th></tr></thead>
          <tbody>{attempt.items.map(item => <tr key={item.itemId}>
            <th scope="row">{item.position}</th>
            <td>{item.selectedKey ?? "Bỏ trống"}</td>
            <td>{item.correctKey ?? "—"}</td>
            <td>{item.awardedPoints === null ? "Chờ chấm" : `${item.awardedPoints} / ${item.points}`}</td>
          </tr>)}</tbody>
        </table></div>
        {attempt.grades.length > 0 && <section aria-label="Lịch sử chấm điểm"><h3>Lịch sử chấm điểm</h3>
          <ul className={styles.list}>{attempt.grades.map(g => <li key={g.revisionNo} className={styles.item}>
            <div><strong>Lần chấm {g.revisionNo}: {scoreText(g.score, g.maxScore)}</strong>
              <small>{g.approvalMode === "automatic" ? "Tự động" : "Giáo viên"} · {dateTime(g.approvedAt)}{g.reason ? ` · ${g.reason}` : ""}</small></div>
            {g.isCurrent && <Chip label="Hiện tại" />}
          </li>)}</ul></section>}
        {(attempt.status === "submitted" || attempt.status === "graded") && <form onSubmit={event => void override(event)} noValidate aria-label="Điều chỉnh điểm">
          <h3>Điều chỉnh điểm</h3>
          <label className={styles.field}><span>Điểm mới *</span><input inputMode="decimal" value={score} onChange={e => setScore(e.target.value)} required /></label>
          <label className={styles.field}><span>Lý do *</span><textarea rows={3} maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} required /></label>
          <div className={styles.actions}><button className="button button-primary" type="submit" disabled={saving}>{saving ? "Đang lưu…" : "Điều chỉnh điểm"}</button></div>
        </form>}
      </>}
      {notice && <p role="status" aria-live="polite" className={styles.notice}>{notice}</p>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <div className={styles.actions}><button className="button button-secondary" onClick={onClose}>Đóng</button></div>
    </div>
  </Modal>;
}
