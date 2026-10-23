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
type Roster = components["schemas"]["RosterDTO"];
type Entry = components["schemas"]["RosterEntryDTO"];
type Invitation = components["schemas"]["InvitationCreatedDTO"];
const STATUS: Record<Entry["status"], [string, string | undefined]> = { active: ["Đang học", undefined], invited: ["Đã mời", "info"], withdrawn: ["Đã rút", "warn"] };
const fmt = (value: string) => new Date(value).toLocaleString("vi-VN");

export function ClassDetailScreen({ classId }: { classId: string }) {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const [klass, setKlass] = useState<ClassDTO | null>(null);
  const [roster, setRoster] = useState<Roster | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [inviting, setInviting] = useState(false);
  const [invitation, setInvitation] = useState<Invitation | null>(null);
  const [copied, setCopied] = useState("");
  const [options, setOptions] = useState({ expiresInHours: "168", maxUses: "1" });
  const [withdraw, setWithdraw] = useState<Entry | null>(null);
  const epoch = useRef(0);
  const invalidate = useCallback(() => { epoch.current++; }, []);
  const base = workspace ? `/api/backend/workspaces/${workspace.id}/classes/${classId}` : "";

  const load = useCallback(async () => {
    if (!base) return;
    const version = ++epoch.current;
    setLoading(true); setError("");
    try {
      const [detail, list] = await Promise.all([read(base), read(base + "/roster")]);
      if (version !== epoch.current) return;
      setKlass(detail); setRoster(list);
    } catch (e) { if (version === epoch.current) setError(handle(e)); }
    finally { if (version === epoch.current) setLoading(false); }
  }, [base, handle]);
  // Network synchronization once the workspace is known.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); return invalidate; }, [load, invalidate]);

  function closeInvite() { setInviting(false); setInvitation(null); setCopied(""); setError(""); }
  async function createInvite(event: FormEvent) {
    event.preventDefault();
    setLoading(true); setError(""); setCopied("");
    try {
      const created: Invitation = await read(base + "/invitations", jsonInit(csrf, { expiresInHours: Number(options.expiresInHours), maxUses: Number(options.maxUses) }));
      setInvitation(created);
    } catch (e) { setError(handle(e)); }
    finally { setLoading(false); }
  }
  async function copy() {
    if (!invitation) return;
    try { await navigator.clipboard.writeText(`${window.location.origin}/join/${invitation.token}`); setCopied("Đã sao chép liên kết mời."); }
    catch { setCopied("Không thể sao chép tự động. Hãy chọn và sao chép thủ công."); }
  }
  async function revoke() {
    if (!invitation) return;
    setLoading(true); setError("");
    try {
      await read(`${base}/invitations/${invitation.id}/revoke`, jsonInit(csrf));
      closeInvite(); setNotice("Đã thu hồi mã mời.");
    } catch (e) { setError(handle(e)); }
    finally { setLoading(false); }
  }
  async function doWithdraw(entry: Entry) {
    setWithdraw(null); setLoading(true); setError(""); setNotice("");
    try {
      await read(`${base}/enrollments/${entry.enrollmentId}/withdraw`, jsonInit(csrf));
      setNotice("Đã cho học sinh rút khỏi lớp.");
      await load();
    } catch (e) { setError(handle(e)); setLoading(false); }
  }

  return <div className={styles.page}><div className={styles.wrap}>
    <TeachingNav current="classes" />
    <Link href="/dashboard/classes" className={styles.muted}>← Danh sách lớp</Link>
    <section className={styles.card} aria-busy={loading || phase === "loading"}>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {klass && <div className={styles.head}><div><h1>{klass.name}</h1><p className={styles.muted}>{[klass.gradeLevel, klass.subject, klass.academicYear].filter(Boolean).join(" · ")}</p></div>
        <span className={styles.chip} data-tone={klass.status === "active" ? undefined : "warn"}>{klass.status === "active" ? "Đang hoạt động" : "Đã lưu trữ"}</span></div>}
      {notice && <p role="status" aria-live="polite">{notice}</p>}
      {error && !inviting && <p role="alert" className={styles.error}>{error} <button className="button button-secondary" onClick={() => void load()}>Tải lại</button></p>}
      {klass?.status === "active" && <div className={styles.actions}><button className="button button-primary" disabled={loading} onClick={() => setInviting(true)}>Tạo mã mời</button></div>}
    </section>
    {roster && <section className={styles.card} aria-label="Danh sách học sinh">
      <h2>Học sinh</h2>
      <div className={styles.counts}><div><strong>{roster.counts.enrolled}</strong>Đang học</div><div><strong>{roster.counts.invited}</strong>Đã mời</div><div><strong>{roster.counts.withdrawn}</strong>Đã rút</div></div>
      {roster.items.length === 0 ? <p className={styles.muted}>Lớp chưa có học sinh. Tạo mã mời và gửi cho học sinh để tham gia.</p> :
        <ul className={styles.list}>{roster.items.map(entry => <li key={entry.enrollmentId} className={styles.item}>
          <div><strong>{entry.displayName}</strong><small>{entry.joinedAt ? "Tham gia " + fmt(entry.joinedAt) : "Chưa tham gia"}{entry.withdrawnAt ? " · Rút " + fmt(entry.withdrawnAt) : ""}</small></div>
          <span className={styles.chip} data-tone={STATUS[entry.status][1]}>{STATUS[entry.status][0]}</span>
          {entry.status !== "withdrawn" && <button className="button button-secondary" disabled={loading} onClick={() => setWithdraw(entry)} aria-label={`Cho ${entry.displayName} rút khỏi lớp`}>Rút khỏi lớp</button>}
        </li>)}</ul>}
    </section>}
    {inviting && <Modal title="Tạo mã mời" onClose={closeInvite}>
      {!invitation ? <form onSubmit={event => void createInvite(event)}>
        <label className={styles.field}><span>Hiệu lực (giờ, 1–720)</span><input type="number" min={1} max={720} required value={options.expiresInHours} onChange={e => setOptions({ ...options, expiresInHours: e.target.value })} /></label>
        <label className={styles.field}><span>Số lần dùng tối đa</span><input type="number" min={1} required value={options.maxUses} onChange={e => setOptions({ ...options, maxUses: e.target.value })} /></label>
        {error && <p role="alert" className={styles.error}>{error}</p>}
        <div className={styles.actions}><button className="button button-primary" type="submit" disabled={loading}>Tạo mã</button><button type="button" className="button button-secondary" onClick={closeInvite}>Hủy</button></div>
      </form> : <div style={{ display: "grid", gap: 14 }}>
        <p>Mã mời chỉ hiển thị một lần. Hãy sao chép và gửi cho học sinh ngay.</p>
        <code className={styles.token} aria-label="Liên kết mời">{`${window.location.origin}/join/${invitation.token}`}</code>
        <p className={styles.muted}>Hết hạn: {fmt(invitation.expiresAt)} · Tối đa {invitation.maxUses} lượt dùng</p>
        {copied && <p role="status" aria-live="polite">{copied}</p>}
        {error && <p role="alert" className={styles.error}>{error}</p>}
        <div className={styles.actions}><button className="button button-primary" onClick={() => void copy()}>Sao chép liên kết</button><button className="button button-secondary" disabled={loading} onClick={() => void revoke()}>Thu hồi mã</button><button className="button button-secondary" onClick={closeInvite}>Đóng</button></div>
      </div>}
    </Modal>}
    {withdraw && <Modal title="Cho học sinh rút khỏi lớp?" onClose={() => setWithdraw(null)}>
      <p>{withdraw.displayName} sẽ không còn là thành viên của lớp. Hành động này không thể hoàn tác từ giao diện.</p>
      <div className={styles.actions}><button className="button button-primary" onClick={() => void doWithdraw(withdraw)}>Xác nhận</button><button className="button button-secondary" onClick={() => setWithdraw(null)}>Hủy</button></div>
    </Modal>}
  </div></div>;
}
