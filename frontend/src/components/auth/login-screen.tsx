"use client";

import Link from "next/link";
import { BookOpen, ArrowRight, LoaderCircle } from "lucide-react";
import { useEffect, useRef } from "react";
import { useAuth } from "./auth-provider";
import type { MockScenario } from "@/lib/auth/types";
import styles from "./mock-auth.module.css";

const messages = {
  idle: "Bạn có thể khám phá giao diện bằng tài khoản mẫu.",
  loading: "Đang đăng nhập thử…",
  success: "Đăng nhập thử thành công.",
  error: "Chưa thể đăng nhập thử. Vui lòng thử lại.",
  cancelled: "Bạn đã hủy bước xác nhận đăng nhập. Có thể thử lại bất cứ lúc nào.",
  expired: "Phiên minh họa đã hết hạn. Hãy đăng nhập thử lại.",
};

export function LoginScreen() {
  const { state, scenario, setScenario, signIn, signOut, cancelSignIn, session } = useAuth();
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    title.current?.focus();
    return cancelSignIn;
  }, [cancelSignIn]);
  const loading = state === "loading";
  return <div className={styles.layout}>
    <section className={styles.story} aria-label="Giới thiệu Eduvia">
      <Link href="/" className="brand" aria-label="Eduvia · Xem bản mẫu"><span className="brand-mark"><BookOpen size={24} /></span><span>eduvia.</span></Link>
      <p className={styles.eyebrow}>KHÔNG GIAN GIẢNG DẠY</p>
      <h2>Thêm thời gian<br />cho những <em>bài học hay.</em></h2>
      <p>Khám phá không gian học liệu, lớp học và những ý tưởng giảng dạy của bạn.</p>
      <span className={styles.footnote}>Eduvia · Dữ liệu minh họa</span>
    </section>
    <section className={styles.form} aria-labelledby="login-title">
      <div className={styles.card}>
        <span className={styles.badge}>Bản mẫu tương tác</span>
        <h1 id="login-title" ref={title} tabIndex={-1}>Chào mừng đến Eduvia</h1>
        <p className={styles.notice}>Chế độ minh họa — chưa kết nối tài khoản thật</p>
        <p className={styles.message} role={state === "error" ? "alert" : "status"} aria-live={state === "error" ? "assertive" : "polite"} aria-atomic="true">{messages[state]}</p>
        <button className={`button button-primary ${styles.action}`} disabled={loading} aria-busy={loading} onClick={() => void (session ? signOut() : signIn())}>
          {loading && <LoaderCircle size={18} aria-hidden="true" />}
          {loading ? "Đang đăng nhập thử…" : session ? "Đăng xuất thử" : "Đăng nhập thử"}
          {!loading && <ArrowRight size={18} aria-hidden="true" />}
        </button>
        <p className={styles.help}>Không cần mật khẩu. Phiên mẫu được xóa khi tải lại trang.</p>
        {process.env.NODE_ENV === "development" && <fieldset className={styles.scenarios} disabled={loading || !!session}>
          <legend>Kiểm tra trong môi trường phát triển</legend>
          <label htmlFor="auth-scenario">Tình huống đăng nhập</label>
          <select id="auth-scenario" value={scenario} onChange={(event) => setScenario(event.target.value as MockScenario)}>
            <option value="success">Thành công</option><option value="error">Lỗi đăng nhập</option><option value="cancelled">Callback bị hủy</option><option value="expired">Hết hạn sau 5 giây</option>
          </select>
        </fieldset>}
        <Link href="/" onNavigate={cancelSignIn} className={styles.back}>Tiếp tục xem bản mẫu <ArrowRight size={16} aria-hidden="true" /></Link>
      </div>
    </section>
  </div>;
}
