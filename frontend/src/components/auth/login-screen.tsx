import Link from "next/link";
import { BookOpen } from "lucide-react";
import styles from "./mock-auth.module.css";
export function LoginScreen() {
  return <div className={styles.layout}>
    <section className={styles.story}><Link href="/" className="brand"><BookOpen /><span>eduvia.</span></Link><p className={styles.eyebrow}>KHÔNG GIAN GIẢNG DẠY</p><h2>Thêm thời gian<br />cho những <em>bài học hay.</em></h2><p>Không gian cá nhân cho công việc giảng dạy của bạn.</p></section>
    <section className={styles.form}><div className={styles.card}><h1>Chào mừng đến Eduvia</h1><p>Đăng nhập bằng email và mật khẩu trên trang tài khoản bảo mật.</p>
      <a className={`button button-primary ${styles.action}`} href="/auth/login">Đăng nhập</a>
      <a className={`button button-secondary ${styles.action}`} href="/auth/login?screen_hint=signup">Tạo tài khoản</a>
      <p className={styles.help}>Bạn có thể chọn “Quên mật khẩu” trên trang đăng nhập. Tài khoản mới cần xác minh email trước khi mở workspace.</p>
      <Link href="/" className={styles.back}>Xem bản mẫu Eduvia</Link></div></section>
  </div>;
}
