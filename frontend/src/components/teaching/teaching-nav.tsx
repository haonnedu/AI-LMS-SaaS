import Link from "next/link";
import styles from "./teaching.module.css";
export function TeachingNav({ current }: { current: "dashboard" | "classes" | "documents" }) {
  const items = [["dashboard", "/dashboard", "Tổng quan"], ["classes", "/dashboard/classes", "Lớp học"], ["documents", "/dashboard/documents", "Tài liệu"]] as const;
  return <nav className={styles.nav} aria-label="Điều hướng giáo viên">{items.map(([key, href, label]) => <Link key={key} href={href} aria-current={current === key ? "page" : undefined}>{label}</Link>)}</nav>;
}
