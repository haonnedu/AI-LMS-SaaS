"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { components } from "@/lib/api/generated";
import { jsonInit, read } from "@/lib/client/api";
import { buildBlueprintBody, emptyBlueprintBody } from "@/lib/client/authoring";
import { mergeById } from "@/lib/client/library";
import { Chip, dateTime, UnitPicker, type Subject, type Tone } from "./authoring-shared";
import { Modal } from "./modal";
import { TeachingNav } from "./teaching-nav";
import { useTeaching } from "./use-teaching";
import styles from "./teaching.module.css";

type Blueprint = components["schemas"]["BlueprintDTO"];
export const BP_STATUS: Record<Blueprint["status"], [string, Tone]> = { draft: ["Bản nháp", "warn"], validated: ["Đã kiểm tra", "info"], published: ["Đã xuất bản", undefined], archived: ["Đã lưu trữ", "warn"] };

export function BlueprintsScreen() {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const router = useRouter();
  const base = workspace ? `/api/backend/workspaces/${workspace.id}/blueprints` : "";
  const [items, setItems] = useState<Blueprint[]>([]);
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
      const page: { items: Blueprint[]; nextCursor: string | null } = await read(`${base}?${q}`);
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
    <TeachingNav current="blueprints" />
    <section className={styles.card} aria-busy={phase === "loading" || loading}>
      <div className={styles.head}><h1>Ma trận đề</h1>{phase === "ready" && <button className="button button-primary" onClick={() => setCreating(true)}>Tạo ma trận đề</button>}</div>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {phase === "ready" && <>
        <div className={styles.form}><label className={styles.field}><span>Trạng thái</span><select value={status} onChange={e => setStatus(e.target.value)}><option value="">Tất cả</option>{Object.entries(BP_STATUS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}</select></label></div>
        {error && <p role="alert" className={styles.error}>{error}</p>}
        {!loading && !error && items.length === 0 && <p className={styles.muted}>Chưa có ma trận đề nào.</p>}
        <ul className={styles.list}>{items.map(b => <li key={b.id} className={styles.item}>
          <div><strong>{b.title}</strong><small>Lớp {b.grade} · {b.examKind === "periodic" ? "Định kỳ" : "Thi thử"} · {b.durationMinutes} phút · {b.totalPoints} điểm · phiên bản {b.latestVersionNo} · {dateTime(b.updatedAt)}</small></div>
          <Chip label={BP_STATUS[b.status][0]} tone={BP_STATUS[b.status][1]} />
          <Link className="button button-secondary" href={`/dashboard/blueprints/${b.id}`} aria-label={`Mở ${b.title}`}>Mở</Link>
        </li>)}</ul>
        {cursor && <button className="button button-secondary" disabled={loading} onClick={() => void load(cursor)}>Tải thêm</button>}
      </>}
    </section>
    {creating && <CreateDialog base={base} csrf={csrf} onError={handle} onClose={() => setCreating(false)} onCreated={id => router.push(`/dashboard/blueprints/${id}`)} />}
  </div></div>;
}

function CreateDialog({ base, csrf, onError, onClose, onCreated }: { base: string; csrf: string; onError: (e: unknown) => string; onClose: () => void; onCreated: (id: string) => void }) {
  const [form, setForm] = useState({ title: "", examKind: "periodic", durationMinutes: "45", totalPoints: "10", effectiveYear: String(new Date().getFullYear()), provenance: "Giáo viên tự soạn" });
  const [subject, setSubject] = useState<{ subject: Subject | null; grade: number | null }>({ subject: null, grade: null });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const pickSubject = useCallback((s: Subject | null, grade: number | null) => setSubject({ subject: s, grade }), []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const minutes = Number(form.durationMinutes), points = Number(form.totalPoints), year = Number(form.effectiveYear);
    if (!form.title.trim()) { setError("Hãy nhập tên ma trận."); return; }
    if (!subject.subject || !subject.grade) { setError("Hãy chọn môn học và lớp."); return; }
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 600) { setError("Thời gian làm bài không hợp lệ."); return; }
    if (!(points > 0) || points > 1000) { setError("Tổng điểm không hợp lệ."); return; }
    if (!Number.isInteger(year) || year < 2000 || year > 2100) { setError("Năm áp dụng không hợp lệ."); return; }
    if (!form.provenance.trim()) { setError("Hãy nhập nguồn gốc."); return; }
    setSaving(true); setError("");
    try {
      const created: Pick<components["schemas"]["BlueprintDTO"], "id"> = await read(base, jsonInit(csrf, {
        title: form.title.trim(), examKind: form.examKind, durationMinutes: minutes, totalPoints: points, effectiveYear: year, provenance: form.provenance.trim(),
        subjectId: subject.subject.id, grade: subject.grade, body: buildBlueprintBody(emptyBlueprintBody()),
      }));
      onCreated(created.id);
    } catch (e) { setError(onError(e)); setSaving(false); }
  }
  return <Modal title="Tạo ma trận đề" onClose={() => !saving && onClose()}>
    <form onSubmit={event => void submit(event)}>
      <label className={styles.field}><span>Tên ma trận *</span><input value={form.title} maxLength={200} required onChange={e => setForm({ ...form, title: e.target.value })} autoFocus /></label>
      <UnitPicker withUnit={false} required onSubject={pickSubject} onError={onError} />
      <div className={styles.tagGrid}>
        <label className={styles.field}><span>Loại đề</span><select value={form.examKind} onChange={e => setForm({ ...form, examKind: e.target.value })}><option value="periodic">Định kỳ</option><option value="mock">Thi thử</option></select></label>
        <label className={styles.field}><span>Thời gian (phút)</span><input inputMode="numeric" value={form.durationMinutes} onChange={e => setForm({ ...form, durationMinutes: e.target.value })} /></label>
        <label className={styles.field}><span>Tổng điểm</span><input inputMode="decimal" value={form.totalPoints} onChange={e => setForm({ ...form, totalPoints: e.target.value })} /></label>
        <label className={styles.field}><span>Năm áp dụng</span><input inputMode="numeric" value={form.effectiveYear} onChange={e => setForm({ ...form, effectiveYear: e.target.value })} /></label>
      </div>
      <label className={styles.field}><span>Nguồn gốc *</span><input value={form.provenance} maxLength={200} onChange={e => setForm({ ...form, provenance: e.target.value })} /></label>
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <div className={styles.actions}><button className="button button-primary" type="submit" disabled={saving}>{saving ? "Đang tạo…" : "Tạo và mở"}</button><button className="button button-secondary" type="button" disabled={saving} onClick={onClose}>Hủy</button></div>
    </form>
  </Modal>;
}
