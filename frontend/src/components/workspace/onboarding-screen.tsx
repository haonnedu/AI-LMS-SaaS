"use client";

import Link from "next/link";
import { ArrowRight, BookOpen, Check, LoaderCircle } from "lucide-react";
import { useEffect, useRef } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { useWorkspace } from "./workspace-provider";
import type { WorkspaceScenario } from "@/lib/workspace/types";
import styles from "./workspace.module.css";

export function OnboardingScreen() {
  const { session, signOut } = useAuth();
  const { workspace, state, scenario, canChooseScenario, chooseScenario, openWorkspace, cancelPending } = useWorkspace();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
    return cancelPending;
  }, [cancelPending]);
  const loading = state === "loading";
  const message = loading ? "Đang chuẩn bị không gian mẫu…" : state === "error"
    ? "Chưa thể chuẩn bị không gian mẫu. Bạn có thể thử lại."
    : workspace ? "Không gian mẫu của bạn đã sẵn sàng."
    : "Học liệu và lớp học sẽ có một nơi riêng để bạn quản lý.";

  return <div className={styles.page}>
    <Link href="/" onNavigate={cancelPending} className="brand" aria-label="Eduvia · Xem bản mẫu"><span className="brand-mark"><BookOpen size={24} /></span><span>eduvia.</span></Link>
    <section className={styles.card} aria-labelledby="onboarding-title">
      <span className={styles.badge}>Bản mẫu tương tác</span>
      <h1 ref={heading} id="onboarding-title" tabIndex={-1}>Không gian riêng cho những bài học hay</h1>
      <p className={styles.notice}>Chế độ minh họa — chưa kết nối tài khoản thật</p>
      {session ? <>
        <p>Xin chào, <strong>{session.user.name}</strong>.</p>
        <p>Không gian cá nhân giúp bạn sắp xếp công việc giảng dạy. Ở bản mẫu này, dữ liệu chỉ được giữ trong phiên xem.</p>
        {workspace && <div className={styles.workspace}><Check size={20} aria-hidden="true" /><div><strong>{workspace.name}</strong><small>Không gian cá nhân · Dữ liệu minh họa</small></div></div>}
        <p className={styles.message} role={state === "error" ? "alert" : "status"} aria-live={state === "error" ? "assertive" : "polite"} aria-atomic="true">{message}</p>
        <button className={`button button-primary ${styles.action}`} disabled={loading} aria-busy={loading} onClick={() => void openWorkspace()}>
          {loading && <LoaderCircle size={18} aria-hidden="true" />}
          {loading ? "Đang chuẩn bị…" : workspace ? "Vào không gian mẫu" : state === "error" ? "Thử lại" : "Mở không gian mẫu"}
          {!loading && <ArrowRight size={18} aria-hidden="true" />}
        </button>
        {process.env.NODE_ENV === "development" && <fieldset className={styles.scenarios} disabled={!canChooseScenario}>
          <legend>Kiểm tra trong môi trường phát triển</legend>
          <label htmlFor="workspace-scenario">Tình huống workspace</label>
          <select id="workspace-scenario" value={scenario} onChange={event => chooseScenario(event.target.value as WorkspaceScenario)}>
            <option value="success">Thành công</option><option value="existing">Đã có workspace</option><option value="error_once">Lỗi lần đầu</option>
          </select>
        </fieldset>}
        <button className={`button button-secondary ${styles.logout}`} onClick={() => { cancelPending(); void signOut(); }}>Đăng xuất thử</button>
      </> : <>
        <p>Đăng nhập thử để khám phá không gian cá nhân mẫu. Bạn vẫn có thể xem các trang minh họa.</p>
        <Link href="/login" className={`button button-primary ${styles.action}`}>Đăng nhập thử <ArrowRight size={18} aria-hidden="true" /></Link>
      </>}
      <Link href="/" onNavigate={cancelPending} className={styles.back}>Tiếp tục xem bản mẫu <ArrowRight size={16} aria-hidden="true" /></Link>
      <small className={styles.help}>Phiên và không gian mẫu được xóa khi tải lại trang.</small>
    </section>
  </div>;
}
