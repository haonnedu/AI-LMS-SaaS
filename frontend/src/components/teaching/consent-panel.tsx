"use client";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { usePrivacyRequest } from "@/components/privacy/use-privacy-request";
import { jsonInit, read } from "@/lib/client/api";
import { activeConsentId, consentLabel, consentLinkUrl, consentMethodLabel, consentTone, isMinor, latestPolicyVersion, requestStatusText, safeDownloadUrl, isRequestTerminal } from "@/lib/client/privacy";
import type { ClassConsentItem, ClassConsents, ConsentLinkCreated, ConsentMethod } from "@/lib/client/privacy-types";
import { Modal } from "./modal";
import styles from "./teaching.module.css";

const fmt = (value: string) => new Date(value).toLocaleString("vi-VN");
type Dialog = { kind: "record" | "link" | "revoke"; student: ClassConsentItem } | null;

function StudentDataActions({ student, wsBase, csrf, handle, disabled, onErased }: { student: ClassConsentItem; wsBase: string; csrf: string; handle: (error: unknown) => string; disabled: boolean; onErased: () => void }) {
  const opts = { createUrl: `${wsBase}/students/${student.studentId}/privacy-requests`, pollUrl: (id: string) => `${wsBase}/privacy-requests/${id}`, csrf, handle };
  const exporter = usePrivacyRequest(opts);
  const eraser = usePrivacyRequest({ ...opts, onSettled: request => { if (request.kind === "erasure" && isRequestTerminal(request.status)) onErased(); } });
  const [confirm, setConfirm] = useState(false);
  const link = safeDownloadUrl(exporter.request?.downloadUrl);
  const exporting = exporter.busy || (exporter.request !== null && !link && !isRequestTerminal(exporter.request.status) && !exporter.gaveUp);
  return <>
    <button className="button button-secondary" disabled={disabled || exporting} onClick={() => void exporter.start("export")} aria-label={`Xuất dữ liệu của ${student.displayName}`}>{exporting ? "Đang xuất…" : "Xuất dữ liệu"}</button>
    <button className="button button-secondary" disabled={disabled || eraser.busy || eraser.request !== null} onClick={() => setConfirm(true)} aria-label={`Xóa dữ liệu của ${student.displayName}`}>Xóa dữ liệu</button>
    <div role="status" aria-live="polite" style={{ flexBasis: "100%", display: "grid", gap: 4 }}>
      {exporter.request && !link && <small>{exporter.gaveUp ? "Việc xuất đang lâu hơn bình thường. Hãy tải lại trang sau ít phút." : requestStatusText("export", exporter.request.status)}</small>}
      {link && <small><a href={link} rel="noreferrer" download>Tải bản sao dữ liệu của {student.displayName}</a>{exporter.request?.downloadExpiresAt ? ` (đến ${fmt(exporter.request.downloadExpiresAt)})` : ""}</small>}
      {eraser.request && <small>{eraser.gaveUp ? "Yêu cầu xóa đã được ghi nhận và đang xử lý." : requestStatusText("erasure", eraser.request.status)}</small>}
    </div>
    {(exporter.error || eraser.error) && <p role="alert" className={styles.error} style={{ flexBasis: "100%", margin: 0 }}>{exporter.error || eraser.error}</p>}
    {confirm && <Modal title="Xóa dữ liệu của học sinh?" onClose={() => setConfirm(false)}>
      <p>Dữ liệu cá nhân của <strong>{student.displayName}</strong> sẽ bị xóa hoặc ẩn danh hóa (tên, email, mã học sinh). Học sinh sẽ không đăng nhập lại vào lớp được. Bài làm và điểm có thể bị xóa hoặc chỉ còn dạng không kèm danh tính. Không thể hoàn tác.</p>
      <p className={styles.muted}>Nếu cần giữ lại bản sao, hãy chọn &quot;Xuất dữ liệu&quot; trước.</p>
      <div className={styles.actions}>
        <button className="button button-primary" onClick={() => { setConfirm(false); void eraser.start("erasure"); }}>Xác nhận xóa</button>
        <button className="button button-secondary" onClick={() => setConfirm(false)}>Hủy</button>
      </div>
    </Modal>}
  </>;
}

/** Teacher consent tab. Guardian contact is write-only here: it is never displayed after submission. */
export function ConsentPanel({ workspaceId, classId, csrf, handle, readOnly }: { workspaceId: string; classId: string; csrf: string; handle: (error: unknown) => string; readOnly: boolean }) {
  const wsBase = `/api/backend/workspaces/${workspaceId}`;
  const [data, setData] = useState<ClassConsents | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [link, setLink] = useState<ConsentLinkCreated | null>(null);
  const [copied, setCopied] = useState("");
  const [form, setForm] = useState({ method: "paper_school" as ConsentMethod, guardianName: "", guardianContact: "", evidenceNote: "", reason: "" });
  const epoch = useRef(0);
  const invalidate = useCallback(() => { epoch.current++; }, []);

  const load = useCallback(async () => {
    const version = ++epoch.current;
    setLoading(true); setError("");
    try {
      const res: ClassConsents = await read(`${wsBase}/classes/${classId}/consents`);
      if (version === epoch.current) setData(res);
    } catch (e) { if (version === epoch.current) setError(handle(e)); }
    finally { if (version === epoch.current) setLoading(false); }
  }, [wsBase, classId, handle]);
  // Network synchronization when the tab opens.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); return invalidate; }, [load, invalidate]);

  function close() { setDialog(null); setLink(null); setCopied(""); setError(""); setForm({ method: "paper_school", guardianName: "", guardianContact: "", evidenceNote: "", reason: "" }); }
  async function act(run: () => Promise<void>, done: string) {
    setLoading(true); setError(""); setNotice("");
    try { await run(); close(); setNotice(done); await load(); }
    catch (e) { setError(handle(e)); setLoading(false); }
  }
  function record(event: FormEvent) {
    event.preventDefault();
    if (!dialog) return;
    const body: Record<string, string> = { method: form.method };
    if (form.method === "paper_school") { body.guardianName = form.guardianName.trim(); if (form.guardianContact.trim()) body.guardianContact = form.guardianContact.trim(); }
    if (form.evidenceNote.trim()) body.evidenceNote = form.evidenceNote.trim();
    void act(async () => { await read(`${wsBase}/students/${dialog.student.studentId}/consents`, jsonInit(csrf, body)); }, "Đã ghi nhận sự đồng ý.");
  }
  function revoke(event: FormEvent) {
    event.preventDefault();
    if (!dialog) return;
    const consentId = activeConsentId(dialog.student.consents);
    if (!consentId) { setError("Không tìm thấy sự đồng ý đang có hiệu lực."); return; }
    void act(async () => { await read(`${wsBase}/students/${dialog.student.studentId}/consents/${consentId}/revoke`, jsonInit(csrf, { reason: form.reason.trim() })); }, "Đã thu hồi sự đồng ý.");
  }
  async function createLink(student: ClassConsentItem) {
    setDialog({ kind: "link", student }); setLink(null); setCopied(""); setError(""); setLoading(true);
    try { setLink(await read(`${wsBase}/students/${student.studentId}/consent-links`, jsonInit(csrf))); }
    catch (e) { setError(handle(e)); }
    finally { setLoading(false); }
  }
  async function copy() {
    if (!link) return;
    try { await navigator.clipboard.writeText(consentLinkUrl(window.location.origin, link.token)); setCopied("Đã sao chép liên kết."); }
    catch { setCopied("Không thể sao chép tự động. Hãy chọn và sao chép thủ công."); }
  }

  const policyVersion = data ? latestPolicyVersion(data.items) : null;
  const summary = data?.summary;
  const chips: [string, number | undefined, string | undefined][] = [["Đã đồng ý", summary?.granted, undefined], ["Đang chờ", summary?.pending, "warn"], ["Không cần", summary?.notRequired, undefined], ["Đã thu hồi", summary?.revoked, "error"], ["Chưa rõ", summary?.unknown, "info"]];
  const minorSelf = dialog?.kind === "record" && isMinor(dialog.student.birthYear);

  return <section className={styles.card} aria-label="Đồng ý phụ huynh" aria-busy={loading}>
    <h2>Đồng ý phụ huynh</h2>
    <p className={styles.muted}>Học sinh dưới 16 tuổi cần phụ huynh đồng ý trước khi làm bài. Thông tin liên hệ của phụ huynh chỉ được gửi đi, không hiển thị lại.</p>
    {summary && <div className={styles.counts} role="group" aria-label="Tóm tắt đồng ý">{chips.map(([label, value, tone]) => <div key={label}><strong>{value ?? 0}</strong><span className={styles.chip} data-tone={tone}>{label}</span></div>)}</div>}
    {notice && <p role="status" aria-live="polite" className={styles.notice}>{notice}</p>}
    {error && !dialog && <p role="alert" className={styles.error}>{error} <button className="button button-secondary" onClick={() => void load()}>Tải lại</button></p>}
    {loading && !data && <p role="status">Đang tải…</p>}
    {data && data.items.length === 0 && <p className={styles.muted}>Lớp chưa có học sinh.</p>}
    {data && data.items.length > 0 && <ul className={styles.list}>{data.items.map(student => {
      const active = activeConsentId(student.consents);
      const canRecord = !readOnly && (student.consentStatus === "unknown" || student.consentStatus === "pending" || student.consentStatus === "revoked");
      return <li key={student.studentId} className={styles.item}>
        <div><strong>{student.displayName}</strong><small>{student.birthYear ? `Sinh năm ${student.birthYear}` : "Chưa có năm sinh"}{student.consents.length ? ` · ${consentMethodLabel(student.consents[0].method)}` : ""}</small></div>
        <span className={styles.chip} data-tone={consentTone(student.consentStatus)}>{consentLabel(student.consentStatus)}</span>
        <div className={styles.actions} style={{ flexBasis: "100%", flexGrow: 1 }}>
          {canRecord && <button className="button button-secondary" disabled={loading} onClick={() => setDialog({ kind: "record", student })} aria-label={`Ghi nhận đồng ý cho ${student.displayName}`}>Ghi nhận đồng ý</button>}
          {canRecord && <button className="button button-secondary" disabled={loading} onClick={() => void createLink(student)} aria-label={`Tạo link phụ huynh cho ${student.displayName}`}>Tạo link phụ huynh</button>}
          {!readOnly && active && <button className="button button-secondary" disabled={loading} onClick={() => setDialog({ kind: "revoke", student })} aria-label={`Thu hồi đồng ý của ${student.displayName}`}>Thu hồi</button>}
          {!readOnly && <StudentDataActions student={student} wsBase={wsBase} csrf={csrf} handle={handle} disabled={loading} onErased={() => void load()} />}
        </div>
      </li>;
    })}</ul>}

    {dialog?.kind === "record" && <Modal title={`Ghi nhận đồng ý · ${dialog.student.displayName}`} onClose={close}>
      <form onSubmit={record}>
        <fieldset className={styles.section}>
          <legend>Cách ghi nhận</legend>
          <label className={styles.check}><input type="radio" name="method" value="paper_school" checked={form.method === "paper_school"} onChange={() => setForm({ ...form, method: "paper_school" })} /><span>Giấy tại trường</span></label>
          <label className={styles.check}><input type="radio" name="method" value="self_adult" checked={form.method === "self_adult"} onChange={() => setForm({ ...form, method: "self_adult" })} /><span>Học sinh đủ tuổi tự đồng ý</span></label>
        </fieldset>
        {form.method === "self_adult" && minorSelf && <p role="alert" className={styles.error}>Học sinh này chưa đủ 16 tuổi theo năm sinh đã khai. Cách này thường chỉ dùng cho học sinh đủ tuổi.</p>}
        {form.method === "paper_school" && <>
          <label className={styles.field}><span>Họ tên phụ huynh</span><input required maxLength={120} value={form.guardianName} onChange={e => setForm({ ...form, guardianName: e.target.value })} autoComplete="off" /></label>
          <label className={styles.field}><span>Liên hệ phụ huynh (email hoặc điện thoại, không bắt buộc)</span><input maxLength={160} value={form.guardianContact} onChange={e => setForm({ ...form, guardianContact: e.target.value })} autoComplete="off" /></label>
        </>}
        <label className={styles.field}><span>Ghi chú bằng chứng (ví dụ: số phiếu, ngày thu)</span><textarea rows={3} maxLength={500} value={form.evidenceNote} onChange={e => setForm({ ...form, evidenceNote: e.target.value })} /></label>
        <label className={styles.field}><span>Phiên bản chính sách</span><input readOnly value={policyVersion ?? "Phiên bản hiện hành"} /></label>
        {error && <p role="alert" className={styles.error}>{error}</p>}
        <div className={styles.actions}><button className="button button-primary" type="submit" disabled={loading}>Lưu</button><button type="button" className="button button-secondary" onClick={close}>Hủy</button></div>
      </form>
    </Modal>}

    {dialog?.kind === "link" && <Modal title={`Link phụ huynh · ${dialog.student.displayName}`} onClose={close}>
      <div style={{ display: "grid", gap: 14 }}>
        {loading && !link && <p role="status">Đang tạo liên kết…</p>}
        {link && <>
          <p>Liên kết chỉ hiển thị một lần. Hãy sao chép và gửi cho phụ huynh ngay.</p>
          <code className={styles.token} aria-label="Liên kết cho phụ huynh">{consentLinkUrl(window.location.origin, link.token)}</code>
          <p className={styles.muted}>Hết hạn: {fmt(link.expiresAt)}</p>
        </>}
        {copied && <p role="status" aria-live="polite">{copied}</p>}
        {error && <p role="alert" className={styles.error}>{error}</p>}
        <div className={styles.actions}>{link && <button className="button button-primary" onClick={() => void copy()}>Sao chép liên kết</button>}<button className="button button-secondary" onClick={close}>Đóng</button></div>
      </div>
    </Modal>}

    {dialog?.kind === "revoke" && <Modal title={`Thu hồi đồng ý · ${dialog.student.displayName}`} onClose={close}>
      <form onSubmit={revoke}>
        <p>Sau khi thu hồi, học sinh sẽ không làm bài được cho đến khi có sự đồng ý mới.</p>
        <label className={styles.field}><span>Lý do thu hồi</span><textarea required rows={3} maxLength={500} value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} /></label>
        {error && <p role="alert" className={styles.error}>{error}</p>}
        <div className={styles.actions}><button className="button button-primary" type="submit" disabled={loading || !form.reason.trim()}>Xác nhận thu hồi</button><button type="button" className="button button-secondary" onClick={close}>Hủy</button></div>
      </form>
    </Modal>}
  </section>;
}
