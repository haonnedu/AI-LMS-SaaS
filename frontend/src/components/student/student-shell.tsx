import Link from "next/link";
import type { ReactNode } from "react";
import styles from "./student.module.css";
/** Small mobile-first frame for student pages. Intentionally independent of the teaching nav. */
export function StudentShell({ children, nav = true }: { children: ReactNode; nav?: boolean }) {
  return <div className={styles.shell}>
    <header className={styles.header}>
      <Link href="/student/assignments" className={styles.brandLink} aria-label="Eduvia · Bài được giao">eduvia.</Link>
      {nav && <nav className={styles.headerNav} aria-label="Điều hướng học sinh"><Link href="/student/assignments">Bài được giao</Link><Link href="/student/privacy">Dữ liệu của em</Link></nav>}
    </header>
    {children}
    {nav && <footer className={styles.footer}><Link href="/privacy">Thông báo quyền riêng tư</Link> · <Link href="/terms">Thỏa thuận người dùng</Link></footer>}
  </div>;
}
