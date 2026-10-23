"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { components } from "@/lib/api/generated";
import { jsonInit, read } from "@/lib/client/api";
import { ASSIGNMENT_STATUS, buildAssignmentBody, emptyAssignmentForm, formatDuration, SCORE_RELEASE_LABEL, SOLUTION_RELEASE_LABEL, TIMEZONES, type ScoreRelease, type SolutionRelease } from "@/lib/client/assessment";
import { Chip, dateTime } from "./authoring-shared";
import { Modal } from "./modal";
import { TeachingNav } from "./teaching-nav";
import { useTeaching } from "./use-teaching";
import styles from "./teaching.module.css";

type ClassDTO = components["schemas"]["ClassDTO"];
type Assignment = components["schemas"]["AssignmentDTO"];
type Exam = components["schemas"]["ExamDTO"];
type ExamDetail = components["schemas"]["ExamDetailDTO"];
type Version = components["schemas"]["ExamVersionSummaryDTO"];

export function AssignmentsScreen({ classId }: { classId: string }) {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const [klass, setKlass] = useState<ClassDTO | null>(null);
  const [items, setItems] = useState<Assignment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(false);
  const epoch = useRef(0);
  const base = workspace ? `/api/backend/workspaces/${workspace.id}` : "";

  const load = useCallback(async () => {
    if (!base) return;
    const mine = ++epoch.current;
    setLoading(true); setError("");
    try {
      const [detail, list] = await Promise.all([read(`${base}/classes/${classId}`), read(`${base}/classes/${classId}/assignments`)]);
      if (mine !== epoch.current) return;
      setKlass(detail); setItems(list.items);
    } catch (e) { if (mine === epoch.current) setError(handle(e)); }
    finally { if (mine === epoch.current) setLoading(false); }
  }, [base, classId, handle]);
  // Network synchronization once the workspace is known.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, [load]);

  return <div className={styles.page}><div className={styles.wrap}>
    <TeachingNav current="classes" />
    <Link href={`/dashboard/classes/${classId}`} className={styles.back}>← {klass ? klass.name : "Lớp học"}</Link>
    <section className={styles.card} aria-busy={loading || phase === "loading"}>
      <div className={styles.head}><h1>Bài giao</h1>
        {klass?.status === "active" && <button className="button button-primary" disabled={loading} onClick={() => { setNotice(""); setCreating(true); }}>Giao bài</button>}
      </div>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {notice && <p role="status" aria-live="polite" className={styles.notice}>{notice}</p>}
      {error && <p role="alert" className={styles.error}>{error} <button className="button button-secondary" onClick={() => void load()}>Tải lại</button></p>}
      {!loading && !error && phase === "ready" && items.length === 0 && <p className={styles.muted}>Lớp chưa có bài giao. Chọn &quot;Giao bài&quot; để giao một đề đã xuất bản cho lớp.</p>}
      {items.length > 0 && <ul className={styles.list}>{items.map(item => <li key={item.id} className={styles.item}>
        <div><strong>{item.title}</strong>
          <small>Mở {dateTime(item.opensAt)} · Đóng {item.closesAt ? dateTime(item.closesAt) : "không giới hạn"} · {formatDuration(item.timeLimitSeconds)} · {item.maxAttempts} lần</small></div>
        <Chip label={ASSIGNMENT_STATUS[item.status][0]} tone={ASSIGNMENT_STATUS[item.status][1]} />
        <Link className="button button-secondary" href={`/dashboard/assignments/${item.id}`}>Xem kết quả</Link>
      </li>)}</ul>}
    </section>
    {creating && base && <CreateDialog base={base} classId={classId} csrf={csrf} handle={handle} onClose={() => setCreating(false)} onCreated={() => { setCreating(false); setNotice("Đã tạo bài giao ở trạng thái bản nháp. Mở bài giao để xuất bản."); void load(); }} />}
  </div></div>;
}

function CreateDialog({ base, classId, csrf, handle, onClose, onCreated }: { base: string; classId: string; csrf: string; handle: (e: unknown) => string; onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState(emptyAssignmentForm());
  const [exams, setExams] = useState<Exam[]>([]);
  const [examId, setExamId] = useState("");
  const [versions, setVersions] = useState<Version[]>([]);
  const [loadingExams, setLoadingExams] = useState(true);
  const [loadingVersions, setLoadingVersions] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm(current => ({ ...current, [key]: value }));

  useEffect(() => {
    let live = true;
    read(`${base}/exams?status=published&limit=50`).then(
      (res: { items: Exam[] }) => { if (live) { setExams(res.items); setLoadingExams(false); } },
      (e: unknown) => { if (live) { setError(handle(e)); setLoadingExams(false); } });
    return () => { live = false; };
  }, [base, handle]);

  async function pickExam(id: string) {
    setExamId(id); setVersions([]); set("examVersionId", ""); setError("");
    if (!id) return;
    setLoadingVersions(true);
    try {
      const detail: ExamDetail = await read(`${base}/exams/${id}`);
      const published = detail.versions.filter(v => v.status === "published").sort((a, b) => b.versionNo - a.versionNo);
      setVersions(published);
      if (published.length === 1) set("examVersionId", published[0].id);
      if (published.length === 0) setError("Đề này chưa có phiên bản đã xuất bản.");
      if (!form.title) set("title", detail.title);
    } catch (e) { setError(handle(e)); }
    finally { setLoadingVersions(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    const built = buildAssignmentBody(form);
    if (!built.ok) { setError(built.error); return; }
    setSaving(true); setError("");
    try { await read(`${base}/classes/${classId}/assignments`, jsonInit(csrf, built.body)); onCreated(); }
    catch (e) { setError(handle(e)); setSaving(false); }
  }

  return <Modal title="Giao bài" onClose={onClose}>
    <form onSubmit={event => void submit(event)} noValidate>
      <label className={styles.field}><span>Đề kiểm tra (đã xuất bản) *</span>
        <select value={examId} onChange={e => void pickExam(e.target.value)} disabled={loadingExams} required>
          <option value="">{loadingExams ? "Đang tải…" : exams.length ? "Chọn đề" : "Chưa có đề đã xuất bản"}</option>
          {exams.map(exam => <option key={exam.id} value={exam.id}>{exam.title}</option>)}
        </select></label>
      <label className={styles.field}><span>Phiên bản *</span>
        <select value={form.examVersionId} onChange={e => set("examVersionId", e.target.value)} disabled={!versions.length || loadingVersions} required>
          <option value="">{loadingVersions ? "Đang tải…" : "Chọn phiên bản"}</option>
          {versions.map(v => <option key={v.id} value={v.id}>Phiên bản {v.versionNo} · {v.totalPoints} điểm</option>)}
        </select></label>
      <label className={styles.field}><span>Tiêu đề *</span><input value={form.title} maxLength={200} onChange={e => set("title", e.target.value)} required /></label>
      <label className={styles.field}><span>Hướng dẫn cho học sinh</span><textarea rows={3} maxLength={4000} value={form.instructions} onChange={e => set("instructions", e.target.value)} /></label>
      <label className={styles.field}><span>Múi giờ</span>
        <select value={form.timezone} onChange={e => set("timezone", e.target.value)}>{TIMEZONES.map(tz => <option key={tz} value={tz}>{tz}</option>)}</select></label>
      <div className={styles.form}>
        <label className={styles.field}><span>Mở bài lúc *</span><input type="datetime-local" value={form.opensAt} onChange={e => set("opensAt", e.target.value)} required /></label>
        <label className={styles.field}><span>Đóng bài lúc</span><input type="datetime-local" value={form.closesAt} onChange={e => set("closesAt", e.target.value)} /></label>
        <label className={styles.field}><span>Thời gian làm bài (phút)</span><input type="number" min={1} max={600} inputMode="numeric" placeholder="Không giới hạn" value={form.timeLimitMinutes} onChange={e => set("timeLimitMinutes", e.target.value)} /></label>
        <label className={styles.field}><span>Số lần làm tối đa</span><input type="number" min={1} max={20} inputMode="numeric" value={form.maxAttempts} onChange={e => set("maxAttempts", e.target.value)} required /></label>
      </div>
      <fieldset className={styles.docFilter}><legend>Công bố điểm</legend>
        {(Object.keys(SCORE_RELEASE_LABEL) as ScoreRelease[]).map(key => <label key={key} className={styles.check}><input type="radio" name="scoreRelease" checked={form.scoreRelease === key} onChange={() => set("scoreRelease", key)} /><span>{SCORE_RELEASE_LABEL[key]}</span></label>)}
      </fieldset>
      <fieldset className={styles.docFilter}><legend>Công bố đáp án</legend>
        {(Object.keys(SOLUTION_RELEASE_LABEL) as SolutionRelease[]).map(key => <label key={key} className={styles.check}><input type="radio" name="solutionRelease" checked={form.solutionRelease === key} onChange={() => set("solutionRelease", key)} /><span>{SOLUTION_RELEASE_LABEL[key]}</span></label>)}
      </fieldset>
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <div className={styles.actions}><button className="button button-primary" type="submit" disabled={saving}>{saving ? "Đang tạo…" : "Tạo bài giao"}</button><button type="button" className="button button-secondary" onClick={onClose}>Hủy</button></div>
    </form>
  </Modal>;
}
