import Link from "next/link";
import styles from "@/components/consent/consent.module.css";
import { USER_AGREEMENT_SECTIONS, USER_AGREEMENT_VERSION } from "@/content/user-agreement";

export const metadata = { title: "Thỏa thuận người dùng" };
export default function Page() {
  return <div className={styles.page}><div className={styles.wrap}>
    <Link href="/" className={styles.brand}>eduvia.</Link>
    <article className={styles.card}>
      <h1>Thỏa thuận người dùng</h1>
      <p className={styles.draft}>DỰ THẢO – chưa được pháp lý duyệt</p>
      <p className={styles.muted}>Phiên bản: {USER_AGREEMENT_VERSION}</p>
      {USER_AGREEMENT_SECTIONS.map(section => <section key={section.title}>
        <h2>{section.title}</h2>
        {section.paragraphs.map(paragraph => <p key={paragraph}>{paragraph}</p>)}
      </section>)}
    </article>
    <nav className={styles.footer} aria-label="Liên kết"><Link href="/privacy">Thông báo quyền riêng tư</Link><Link href="/login">Đăng nhập</Link></nav>
  </div></div>;
}
