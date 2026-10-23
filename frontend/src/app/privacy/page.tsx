import Link from "next/link";
import styles from "@/components/consent/consent.module.css";
import { PRIVACY_NOTICE_SECTIONS, PRIVACY_NOTICE_VERSION } from "@/content/privacy-notice";

export const metadata = { title: "Quyền riêng tư" };
export default function Page() {
  return <div className={styles.page}><div className={styles.wrap}>
    <Link href="/" className={styles.brand}>eduvia.</Link>
    <article className={styles.card}>
      <h1>Thông báo quyền riêng tư</h1>
      <p className={styles.draft}>DỰ THẢO – chưa được pháp lý duyệt</p>
      <p className={styles.muted}>Phiên bản: {PRIVACY_NOTICE_VERSION}</p>
      {PRIVACY_NOTICE_SECTIONS.map(section => <section key={section.title}>
        <h2>{section.title}</h2>
        {section.paragraphs.map(paragraph => <p key={paragraph}>{paragraph}</p>)}
      </section>)}
    </article>
    <nav className={styles.footer} aria-label="Liên kết"><Link href="/login">Đăng nhập</Link></nav>
  </div></div>;
}
