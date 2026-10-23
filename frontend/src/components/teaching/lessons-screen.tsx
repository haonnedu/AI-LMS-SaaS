"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { components } from "@/lib/api/generated";
import { jsonInit, read } from "@/lib/client/api";
import { buildBody, emptyBody } from "@/lib/client/authoring";
import { mergeById } from "@/lib/client/library";
import { Chip, dateTime, UnitPicker, unitLabel, type Tone } from "./authoring-shared";
import { Modal } from "./modal";
import { TeachingNav } from "./teaching-nav";
import { useTeaching } from "./use-teaching";
import styles from "./teaching.module.css";

type Item = components["schemas"]["ContentItemDTO"];
export const KIND_LABEL: Record<Item["kind"], string> = { lesson_plan: "Giáo án", study_guide: "Đề cương" };
export const ITEM_STATUS: Record<Item["status"], [string, Tone]> = { draft: ["Bản nháp", "warn"], in_review: ["Chờ duyệt", "info"], published: ["Đã xuất bản", undefined], archived: ["Đã lưu trữ", "warn"] };

export function LessonsScreen() {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const router = useRouter();
  const [items, setItems] = useState<Item[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [create, setCreate] = useState<Item["kind"] | null>(null);
  const [form, setForm] = useState({ title: "", unit: "" });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const epoch = useRef(0);
  const base = workspace ? `/api/backend/workspaces/${workspace.id}/content-items` : "";

  const load = useCallback(async (after: string | null) => {
    if (!base) return;
    const mine = ++epoch.current;
    setLoading(true); setError("");
    try {
      const q = new URLSearchParams({ limit: "25" });
      if (kind) q.set("kind", kind);
      if (status) q.set("status", status);
      if (after) q.set("cursor", after);
      const page: { items: Item[]; nextCursor: string | null } = await read(`${base}?${q}`);
      if (mine !== epoch.current) return;
      setItems(current => after ? mergeById(current, page.items) : page.items);
      setCursor(page.nextCursor);
    } catch (e) { if (mine === epoch.current) setError(handle(e)); }
    finally { if (mine === epoch.current) setLoading(false); }
  }, [base, kind, status, handle]);
  // Network synchronisation when filters or workspace change.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(null); }, [load]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!create) return;
    const title = form.title.trim();
    if (!title) { setFormError("Hãy nhập tiêu đề."); return; }
    setSaving(true); setFormError("");
    try {
      const item: Item = await read(base, jsonInit(csrf, { kind: create, title, curriculumUnitId: form.unit || null, body: buildBody(emptyBody()) }));
      router.push(`/dashboard/lessons/${item.id}`);
    } catch (e) { setFormError(handle(e)); setSaving(false); }
  }
  const open = (k: Item["kind"]) => { setForm({ title: "", unit: "" }); setFormError(""); setSaving(false); setCreate(k); };

  return <div className={styles.page}><div className={styles.wrap}>
    <TeachingNav current="lessons" />
    <section className={styles.card} aria-busy={phase === "loading" || loading}>
      <div className={styles.head}><h1>Soạn bài</h1>
        {phase === "ready" && <div className={styles.actions}>
          <button className="button button-primary" onClick={() => open("lesson_plan")}>Tạo giáo án</button>
          <button className="button button-secondary" onClick={() => open("study_guide")}>Tạo đề cương</button>
        </div>}
      </div>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {phase === "ready" && <>
        <div className={styles.form} role="group" aria-label="Bộ lọc">
          <label className={styles.field}><span>Loại</span><select value={kind} onChange={e => setKind(e.target.value)}><option value="">Tất cả</option><option value="lesson_plan">Giáo án</option><option value="study_guide">Đề cương</option></select></label>
          <label className={styles.field}><span>Trạng thái</span><select value={status} onChange={e => setStatus(e.target.value)}><option value="">Tất cả</option>{Object.entries(ITEM_STATUS).map(([k, [label]]) => <option key={k} value={k}>{label}</option>)}</select></label>
        </div>
        {error && <p role="alert" className={styles.error}>{error}</p>}
        {!loading && !error && items.length === 0 && <p className={styles.muted}>Chưa có nội dung nào. Hãy tạo giáo án hoặc đề cương đầu tiên.</p>}
        <ul className={styles.list}>{items.map(item => <li key={item.id} className={styles.item}>
          <div><strong>{item.title}</strong><small>{KIND_LABEL[item.kind]} · bản {item.latestRevisionNo} · {item.curriculumUnitId ? unitLabel(item.curriculumUnitId) : "Chưa gắn đơn vị"} · cập nhật {dateTime(item.updatedAt)}</small></div>
          <Chip label={ITEM_STATUS[item.status][0]} tone={ITEM_STATUS[item.status][1]} />
          <Link className="button button-secondary" href={`/dashboard/lessons/${item.id}`} aria-label={`Mở ${item.title}`}>Mở</Link>
        </li>)}</ul>
        {cursor && <button className="button button-secondary" disabled={loading} onClick={() => void load(cursor)}>Tải thêm</button>}
      </>}
    </section>
    {create && <Modal title={create === "lesson_plan" ? "Tạo giáo án" : "Tạo đề cương"} onClose={() => !saving && setCreate(null)}>
      <form onSubmit={event => void submit(event)}>
        <label className={styles.field}><span>Tiêu đề *</span><input value={form.title} maxLength={200} required onChange={e => setForm({ ...form, title: e.target.value })} autoFocus /></label>
        <UnitPicker unitId={form.unit} onUnit={unit => setForm(f => ({ ...f, unit }))} onError={handle} />
        {formError && <p role="alert" className={styles.error}>{formError}</p>}
        <div className={styles.actions}><button className="button button-primary" type="submit" disabled={saving}>{saving ? "Đang tạo…" : "Tạo và mở"}</button><button className="button button-secondary" type="button" disabled={saving} onClick={() => setCreate(null)}>Hủy</button></div>
      </form>
    </Modal>}
  </div></div>;
}
