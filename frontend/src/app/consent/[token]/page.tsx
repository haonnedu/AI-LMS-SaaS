import Link from "next/link";
import { ConsentForm } from "@/components/consent/consent-form";
import styles from "@/components/consent/consent.module.css";
import { GUARDIAN_CONSENT_TEXT } from "@/content/consent-text";
import { consentLinkOutcome, givenName, isConsentToken } from "@/lib/client/privacy";
import type { PublicConsentLink } from "@/lib/client/privacy-types";
import { callConsentLink, errorCode } from "@/lib/server/consent-link";

export const dynamic = "force-dynamic";
export const metadata = { title: "Đồng ý của phụ huynh", referrer: "no-referrer", robots: { index: false, follow: false } };
const PROBLEM = {
  invalid: ["Liên kết không đúng", "Xin hãy kiểm tra lại liên kết hoặc nhờ thầy cô gửi liên kết mới."],
  expired: ["Liên kết đã hết hạn", "Xin hãy nhờ thầy cô tạo liên kết mới."],
  used: ["Liên kết đã được dùng", "Sự đồng ý qua liên kết này đã được ghi nhận. Nếu cần, xin nhờ thầy cô tạo liên kết mới."],
  rate_limited: ["Bạn thử quá nhiều lần", "Xin chờ một lúc rồi mở lại liên kết."],
  error: ["Chưa mở được trang", "Dịch vụ tạm thời không khả dụng. Xin thử lại sau ít phút."],
} as const;

export default async function Page({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  let info: PublicConsentLink | null = null;
  let outcome: keyof typeof PROBLEM = "invalid";
  if (isConsentToken(token)) {
    const result = await callConsentLink(token, "GET");
    const kind = consentLinkOutcome(result.status, errorCode(result.payload));
    if (kind === "ok") info = result.payload as PublicConsentLink; else outcome = kind;
  }
  return <div className={styles.page}><div className={styles.wrap}>
    <Link href="/" className={styles.brand}>eduvia.</Link>
    {info ? <section className={styles.card}>
      <h1>{GUARDIAN_CONSENT_TEXT.title}</h1>
      <p className={styles.draft}>DỰ THẢO – chưa được pháp lý duyệt</p>
      <dl className={styles.facts}>
        <div><dt>Học sinh</dt><dd>{givenName(info.studentDisplayName)}</dd></div>
        <div><dt>Trường / nhóm</dt><dd>{info.workspaceName}</dd></div>
        <div><dt>Phiên bản chính sách</dt><dd>{info.policyVersion}</dd></div>
        <div><dt>Liên kết hết hạn lúc</dt><dd>{new Date(info.expiresAt).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" })}</dd></div>
      </dl>
      <div className={styles.text}>{GUARDIAN_CONSENT_TEXT.paragraphs.map(paragraph => <p key={paragraph}>{paragraph}</p>)}</div>
      <ConsentForm token={token} agreeLabel={GUARDIAN_CONSENT_TEXT.checkboxLabel} />
    </section> : <section className={styles.card} role="alert">
      <h1>{PROBLEM[outcome][0]}</h1>
      <p>{PROBLEM[outcome][1]}</p>
    </section>}
    <nav className={styles.footer} aria-label="Liên kết"><Link href="/privacy">Thông báo quyền riêng tư</Link></nav>
  </div></div>;
}
