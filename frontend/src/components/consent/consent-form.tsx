"use client";
import { useRef, useState, type FormEvent } from "react";
import { consentLinkOutcome, type ConsentLinkOutcome } from "@/lib/client/privacy";
import styles from "./consent.module.css";

const MESSAGE: Record<Exclude<ConsentLinkOutcome, "ok">, string> = {
  invalid: "Liên kết này không đúng. Xin hãy kiểm tra lại hoặc nhờ thầy cô gửi liên kết mới.",
  expired: "Liên kết đã hết hạn. Xin hãy nhờ thầy cô tạo liên kết mới.",
  used: "Liên kết này đã được dùng rồi. Nếu cần, xin hãy nhờ thầy cô tạo liên kết mới.",
  rate_limited: "Bạn đã thử quá nhiều lần. Xin chờ một lúc rồi thử lại.",
  error: "Hiện chưa gửi được. Xin thử lại sau ít phút.",
};

/** Guardian form. The guardian's name/contact are sent once to the API and never stored or logged here. */
export function ConsentForm({ token, agreeLabel }: { token: string; agreeLabel: string }) {
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<ConsentLinkOutcome | null>(null);
  const [fieldError, setFieldError] = useState("");
  const sending = useRef(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (sending.current) return;
    const trimmedName = name.trim(), trimmedContact = contact.trim();
    if (!trimmedName) { setFieldError("Xin nhập họ tên phụ huynh."); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedContact) && !/^\+?[0-9 .-]{8,15}$/.test(trimmedContact)) { setFieldError("Xin nhập email hoặc số điện thoại hợp lệ."); return; }
    if (!agree) { setFieldError("Xin đánh dấu ô \"Tôi đồng ý\" để tiếp tục."); return; }
    setFieldError(""); sending.current = true; setBusy(true);
    try {
      const response = await fetch(`/api/public/consent-links/${token}`, { method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store", body: JSON.stringify({ guardianName: trimmedName, guardianContact: trimmedContact, agree: true }), signal: AbortSignal.timeout(15000) });
      let code: string | undefined;
      try { code = (await response.json())?.error?.code; } catch { code = undefined; }
      setOutcome(consentLinkOutcome(response.status, code));
    } catch { setOutcome("error"); }
    finally { sending.current = false; setBusy(false); }
  }

  if (outcome === "ok") return <div role="status" aria-live="polite" className={styles.ok}><strong>Cảm ơn phụ huynh.</strong><br />Sự đồng ý đã được ghi nhận. Bạn có thể đóng trang này.</div>;
  return <form className={styles.form} onSubmit={event => void submit(event)} aria-busy={busy} noValidate>
    <label className={styles.field}><span>Họ và tên phụ huynh</span><input required maxLength={120} autoComplete="name" value={name} onChange={event => setName(event.target.value)} /></label>
    <label className={styles.field}><span>Email hoặc số điện thoại</span><input required maxLength={160} autoComplete="email" inputMode="email" value={contact} onChange={event => setContact(event.target.value)} aria-describedby="contact-help" /><small id="contact-help">Chỉ dùng để xác nhận. Eduvia không lưu lại nguyên văn.</small></label>
    <label className={styles.check}><input type="checkbox" checked={agree} onChange={event => setAgree(event.target.checked)} /><span><strong>Tôi đồng ý.</strong> {agreeLabel}</span></label>
    {fieldError && <p role="alert" className={styles.error}>{fieldError}</p>}
    {outcome && <p role="alert" className={styles.state}>{MESSAGE[outcome]}</p>}
    <button className={styles.btn} type="submit" disabled={busy}>{busy ? "Đang gửi…" : "Gửi sự đồng ý"}</button>
  </form>;
}
