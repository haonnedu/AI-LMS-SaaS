"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { components } from "@/lib/api/generated";
import { jsonInit, read } from "@/lib/client/api";
import { Modal } from "./modal";
import { TeachingNav } from "./teaching-nav";
import { useTeaching } from "./use-teaching";
import styles from "./teaching.module.css";

type ClassDTO = components["schemas"]["ClassDTO"];
export function ClassesScreen() {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const [items, setItems] = useState<ClassDTO[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [filter, setFilter] = useState<"active" | "archived">("active");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirm, setConfirm] = useState<ClassDTO | null>(null);
  const [form, setForm] = useState({ name: "", gradeLevel: "", subject: "", academicYear: "" });
  const epoch = useRef(0);
  const invalidate = useCallback(() => { epoch.current++; }, []);
  const base = workspace ? `/api/backend/workspaces/${workspace.id}/classes` : "";

  const fetchPage = useCallback(async (after: string | null) => {
    if (!base) return;
    const version = ++epoch.current;
    setLoading(true); setError("");
    try {
      const result = await read(`${base}?status=${filter}&limit=20${after ? "&cursor=" + encodeURIComponent(after) : ""}`);
      if (version !== epoch.current) return;
      setItems(current => after ? [...current, ...result.items] : result.items);
      setCursor(result.nextCursor);
    } catch (e) { if (version === epoch.current) setError(handle(e)); }
    finally { if (version === epoch.current) setLoading(false); }
  }, [base, filter, handle]);
  // Network synchronization on workspace/filter change.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void fetchPage(null); return invalidate; }, [fetchPage, invalidate]);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (loading || !base) return;
    const body: Record<string, string> = { name: form.name.trim() };
    for (const key of ["gradeLevel", "subject", "academicYear"] as const) if (form[key].trim()) body[key] = form[key].trim();
    setLoading(true); setError(""); setNotice("");
    try {
      await read(base, jsonInit(csrf, body));
      setForm({ name: "", gradeLevel: "", subject: "", academicYear: "" });
      setNotice("Đã tạo lớp học.");
      setFilter("active");
      await fetchPage(null);
    } catch (e) { setError(handle(e)); setLoading(false); }
  }
  async function archive(item: ClassDTO) {
    setConfirm(null); setLoading(true); setError(""); setNotice("");
    try {
      await read(`${base}/${item.id}/archive`, jsonInit(csrf));
      setNotice(`Đã lưu trữ lớp "${item.name}".`);
      await fetchPage(null);
    } catch (e) { setError(handle(e)); setLoading(false); }
  }

  return <div className={styles.page}><div className={styles.wrap}>
    <TeachingNav current="classes" />
    <section className={styles.card} aria-busy={loading || phase === "loading"}>
      <div className={styles.head}><h1>Lớp học</h1>{workspace && <span className={styles.muted}>{workspace.name}</span>}</div>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {phase === "ready" && <form className={styles.form} onSubmit={event => void create(event)} aria-label="Tạo lớp học">
        <label className={styles.field}><span>Tên lớp (bắt buộc)</span><input required maxLength={200} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
        <label className={styles.field}><span>Khối / cấp</span><input maxLength={50} value={form.gradeLevel} onChange={e => setForm({ ...form, gradeLevel: e.target.value })} /></label>
        <label className={styles.field}><span>Môn học</span><input maxLength={100} value={form.subject} onChange={e => setForm({ ...form, subject: e.target.value })} /></label>
        <label className={styles.field}><span>Năm học</span><input maxLength={20} placeholder="2026-2027" value={form.academicYear} onChange={e => setForm({ ...form, academicYear: e.target.value })} /></label>
        <button className="button button-primary" type="submit" disabled={loading || !form.name.trim()}>Tạo lớp</button>
      </form>}
    </section>
    {phase === "ready" && <section className={styles.card} aria-busy={loading} aria-label="Danh sách lớp">
      <div className={styles.head}><h2>Danh sách lớp</h2>
        <label className={styles.field}><span>Trạng thái</span><select value={filter} onChange={e => setFilter(e.target.value as "active" | "archived")}><option value="active">Đang hoạt động</option><option value="archived">Đã lưu trữ</option></select></label></div>
      {notice && <p role="status" aria-live="polite">{notice}</p>}
      {error && <p role="alert" className={styles.error}>{error} <button className="button button-secondary" onClick={() => void fetchPage(null)}>Tải lại</button></p>}
      {loading && items.length === 0 && <p role="status">Đang tải danh sách…</p>}
      {!loading && !error && items.length === 0 && <p className={styles.muted}>{filter === "active" ? "Bạn chưa có lớp nào. Hãy tạo lớp đầu tiên ở biểu mẫu phía trên." : "Chưa có lớp nào được lưu trữ."}</p>}
      <ul className={styles.list}>{items.map(item => <li key={item.id} className={styles.item}>
        <div><strong>{item.name}</strong><small>{[item.gradeLevel, item.subject, item.academicYear].filter(Boolean).join(" · ") || "Chưa có thông tin bổ sung"}</small></div>
        <span className={styles.chip} data-tone={item.status === "active" ? undefined : "warn"}>{item.status === "active" ? "Đang hoạt động" : "Đã lưu trữ"}</span>
        <div className={styles.actions}>
          <Link className="button button-secondary" href={`/dashboard/classes/${item.id}`} aria-label={`Xem lớp ${item.name}`}>Xem lớp</Link>
          {item.status === "active" && <button className="button button-secondary" disabled={loading} onClick={() => setConfirm(item)} aria-label={`Lưu trữ lớp ${item.name}`}>Lưu trữ</button>}
        </div></li>)}</ul>
      {cursor && <button className="button button-secondary" disabled={loading} onClick={() => void fetchPage(cursor)}>Tải thêm</button>}
    </section>}
    {confirm && <Modal title="Lưu trữ lớp học?" onClose={() => setConfirm(null)}>
      <p>Lớp “{confirm.name}” sẽ được chuyển vào mục đã lưu trữ.</p>
      <div className={styles.actions}><button className="button button-primary" onClick={() => void archive(confirm)}>Lưu trữ</button><button className="button button-secondary" onClick={() => setConfirm(null)}>Hủy</button></div>
    </Modal>}
  </div></div>;
}
