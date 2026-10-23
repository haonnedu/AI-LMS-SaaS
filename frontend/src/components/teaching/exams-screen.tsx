"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { components } from "@/lib/api/generated";
import { jsonInit, read } from "@/lib/client/api";
import { buildManualExam, EXAM_STATUS, totalPoints, type ManualPick } from "@/lib/client/generation";
import { mergeById } from "@/lib/client/library";
import { Chip, dateTime } from "./authoring-shared";
import { Modal } from "./modal";
import { TeachingNav } from "./teaching-nav";
import { useTeaching } from "./use-teaching";
import styles from "./teaching.module.css";

type Exam = components["schemas"]["ExamDTO"];
type Summary = components["schemas"]["QuestionSummaryDTO"];

export function ExamsScreen() {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const router = useRouter();
  const base = workspace ? `/api/backend/workspaces/${workspace.id}/exams` : "";
  const [items, setItems] = useState<Exam[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const epoch = useRef(0);
  const load = useCallback(async (after: string | null) => {
    if (!base) return;
    const mine = ++epoch.current;
    setLoading(true); setError("");
    try {
      const q = new URLSearchParams({ limit: "25" });
      if (status) q.set("status", status);
      if (after) q.set("cursor", after);
      const page: { items: Exam[]; nextCursor: string | null } = await read(`${base}?${q}`);
      if (mine !== epoch.current) return;
      setItems(current => after ? mergeById(current, page.items) : page.items);
      setCursor(page.nextCursor);
    } catch (e) { if (mine === epoch.current) setError(handle(e)); }
    finally { if (mine === epoch.current) setLoading(false); }
  }, [base, status, handle]);
  // Network synchronisation when the filter or workspace changes.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(null); }, [load]);

  return <div className={styles.page}><div className={styles.wrap}>
    <TeachingNav current="exams" />
    <section className={styles.card} aria-busy={phase === "loading" || loading}>
      <div className={styles.head}><h1>Đề kiểm tra</h1>{phase === "ready" && <button className="button button-primary" onClick={() => setCreating(true)}>Tạo đề thủ công</button>}</div>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {phase === "ready" && <>
        <p className={styles.muted}>Để tạo đề từ ma trận, mở một ma trận đề đã xuất bản và chọn “Tạo đề từ ma trận”.</p>
        <div className={styles.form}><label className={styles.field}><span>Trạng thái</span><select value={status} onChange={e => setStatus(e.target.value)}><option value="">Tất cả</option>{Object.entries(EXAM_STATUS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}</select></label></div>
        {error && <p role="alert" className={styles.error}>{error}</p>}
        {!loading && !error && items.length === 0 && <p className={styles.muted}>Chưa có đề kiểm tra nào.</p>}
        <ul className={styles.list}>{items.map(exam => <li key={exam.id} className={styles.item}>
          <div><strong>{exam.title}</strong><small>{exam.blueprintVersionId ? "Tạo từ ma trận" : "Tạo thủ công"} · cập nhật {dateTime(exam.updatedAt)}</small></div>
          <div className={styles.actions}>
            <Chip label={EXAM_STATUS[exam.status][0]} tone={EXAM_STATUS[exam.status][1]} />
            {exam.status === "published" && <Chip label="Đã công bố cho lớp" tone="info" />}
          </div>
          <Link className="button button-secondary" href={`/dashboard/exams/${exam.id}`} aria-label={`Mở ${exam.title}`}>Mở</Link>
        </li>)}</ul>
        {cursor && <button className="button button-secondary" disabled={loading} onClick={() => void load(cursor)}>Tải thêm</button>}
      </>}
    </section>
    {creating && workspace && <ManualDialog wsBase={`/api/backend/workspaces/${workspace.id}`} csrf={csrf} onError={handle} onClose={() => setCreating(false)} onCreated={id => router.push(`/dashboard/exams/${id}`)} />}
  </div></div>;
}

function ManualDialog({ wsBase, csrf, onError, onClose, onCreated }: { wsBase: string; csrf: string; onError: (e: unknown) => string; onClose: () => void; onCreated: (id: string) => void }) {
  const [title, setTitle] = useState("");
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [pool, setPool] = useState<Summary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [picks, setPicks] = useState<ManualPick[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const epoch = useRef(0);
  const load = useCallback(async (after: string | null) => {
    const mine = ++epoch.current;
    setLoading(true);
    try {
      const q = new URLSearchParams({ status: "active", limit: "30" });
      if (applied) q.set("q", applied);
      if (after) q.set("cursor", after);
      const page: { items: Summary[]; nextCursor: string | null } = await read(`${wsBase}/questions?${q}`);
      if (mine !== epoch.current) return;
      setPool(current => after ? mergeById(current, page.items) : page.items);
      setCursor(page.nextCursor); setError("");
    } catch (e) { if (mine === epoch.current) setError(onError(e)); }
    finally { if (mine === epoch.current) setLoading(false); }
  }, [wsBase, applied, onError]);
  // Network synchronisation when the search changes.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(null); }, [load]);

  const toggle = (question: Summary, on: boolean) => {
    setPicks(current => on ? [...current, { id: question.id, points: "0.25" }] : current.filter(p => p.id !== question.id));
  };
  async function submit(event: FormEvent) {
    event.preventDefault();
    const built = buildManualExam(title, picks);
    if (!built.ok) { setError(built.message); return; }
    setSaving(true); setError("");
    try {
      const created: Pick<Exam, "id"> = await read(`${wsBase}/exams`, jsonInit(csrf, built.value), 30000);
      onCreated(created.id);
    } catch (e) { setError(onError(e)); setSaving(false); }
  }
  return <Modal title="Tạo đề thủ công" onClose={() => !saving && onClose()}>
    <form onSubmit={event => void submit(event)}>
      <label className={styles.field}><span>Tên đề *</span><input value={title} maxLength={200} required onChange={e => setTitle(e.target.value)} autoFocus /></label>
      <div className={styles.searchRow}>
        <label className={styles.field}><span>Tìm câu hỏi trong ngân hàng</span><input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); setApplied(query.trim()); } }} /></label>
        <button type="button" className="button button-secondary" onClick={() => setApplied(query.trim())}>Tìm</button>
      </div>
      <div className={styles.pickList} aria-busy={loading}>
        {!loading && pool.length === 0 && <p className={styles.muted}>Không có câu hỏi đang dùng phù hợp.</p>}
        {pool.map(question => {
          const pick = picks.find(p => p.id === question.id);
          return <div key={question.id} className={styles.pickRow}>
            <input type="checkbox" checked={!!pick} aria-label={`Chọn câu: ${question.stem.slice(0, 60)}`} onChange={e => toggle(question, e.target.checked)} />
            <span>{question.stem.length > 140 ? question.stem.slice(0, 140) + "…" : question.stem}</span>
            {pick ? <input className={styles.cell} inputMode="decimal" aria-label={`Điểm cho câu: ${question.stem.slice(0, 40)}`} value={pick.points} onChange={e => setPicks(current => current.map(p => p.id === question.id ? { ...p, points: e.target.value } : p))} /> : <span />}
          </div>;
        })}
      </div>
      {cursor && <button type="button" className="button button-secondary" disabled={loading} onClick={() => void load(cursor)}>Tải thêm câu hỏi</button>}
      <p role="status" className={styles.muted}>Đã chọn {picks.length} câu · tổng {totalPoints(picks)} điểm</p>
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <div className={styles.actions}><button className="button button-primary" type="submit" disabled={saving}>{saving ? "Đang tạo…" : "Tạo đề"}</button><button className="button button-secondary" type="button" disabled={saving} onClick={onClose}>Hủy</button></div>
    </form>
  </Modal>;
}
