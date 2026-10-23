"use client";
import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import styles from "./mock-auth.module.css";

const subscribe = () => () => {};
export function PasswordLogin({ initialMode = "login", google = false }: { initialMode?: "login" | "signup" | "forgot" | "reset" | "verify"; google?: boolean }) {
  const router = useRouter();
  const hydrated = useSyncExternalStore(subscribe, () => true, () => false);
  const [mode, setMode] = useState(initialMode), [email, setEmail] = useState(""), [password, setPassword] = useState(""), [name, setName] = useState("");
  const [message, setMessage] = useState(""), [busy, setBusy] = useState(false);
  async function submit(social = false) {
    setBusy(true); setMessage("");
    try {
      const path = social ? "sign-in/social" : ({ login: "sign-in/email", signup: "sign-up/email", forgot: "request-password-reset", reset: "reset-password", verify: "send-verification-email" })[mode];
      const body = social ? { provider: "google", callbackURL: "/onboarding", errorCallbackURL: "/login", disableRedirect: true } : mode === "forgot" ? { email, redirectTo: "/reset-password" } : mode === "reset" ? { newPassword: password, token: new URLSearchParams(window.location.search).get("token") } : mode === "verify" ? { email, callbackURL: "/login" } : { email, password, name, callbackURL: "/login" };
      const response = await fetch("/api/auth/" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || result.message || "Không thể hoàn thành. Vui lòng thử lại.");
      if (social) { const url = new URL(result.url); if (url.protocol !== "https:") throw new Error("Đường dẫn không hợp lệ."); window.location.assign(url.href); }
      else if (mode === "login") router.replace("/onboarding");
      else if (mode === "signup") { setMode("verify"); setPassword(""); setMessage("Kiểm tra email để xác minh tài khoản, sau đó đăng nhập."); }
      else if (mode === "reset") { setMode("login"); setPassword(""); setMessage("Đã đặt mật khẩu. Vui lòng đăng nhập lại."); }
      else setMessage("Nếu email hợp lệ, bạn sẽ nhận được hướng dẫn. Kiểm tra cả thư rác.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Dịch vụ tạm thời không khả dụng."); }
    finally { setBusy(false); }
  }
  return <div className={styles.layout}><section className={styles.story}><Link href="/" className="brand">eduvia.</Link><p className={styles.eyebrow}>KHÔNG GIAN GIẢNG DẠY</p><h2>Thêm thời gian<br />cho những <em>bài học hay.</em></h2><p>Một tài khoản, nhiều cách đăng nhập. Workspace của bạn luôn được giữ nguyên khi liên kết tài khoản.</p></section><section className={styles.form}><div className={styles.card}>
    <h1>{{ login: "Đăng nhập Eduvia", signup: "Tạo tài khoản Eduvia", forgot: "Quên mật khẩu", reset: "Đặt mật khẩu mới", verify: "Xác minh email" }[mode]}</h1>
    <form className={styles.fields} onSubmit={event => { event.preventDefault(); void submit(); }}>
      {mode === "signup" && <label>Tên<input disabled={busy || !hydrated} required value={name} onChange={event => setName(event.target.value)} maxLength={255} autoComplete="name" /></label>}
      {mode !== "reset" && <label>Email<input disabled={busy || !hydrated} required type="email" value={email} onChange={event => setEmail(event.target.value)} autoComplete="email" /></label>}
      {["login", "signup", "reset"].includes(mode) && <label>Mật khẩu<input disabled={busy || !hydrated} required type="password" minLength={mode === "login" ? 1 : 12} maxLength={128} value={password} onChange={event => setPassword(event.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>}
      <button disabled={busy || !hydrated} className={`button button-primary ${styles.action}`}>{busy ? "Đang xử lý…" : mode === "verify" ? "Gửi lại email xác minh" : "Tiếp tục"}</button>
    </form>
    {message && <p role="status">{message}</p>}
    {google && mode === "login" && <button disabled={busy || !hydrated} className="button button-secondary" onClick={() => void submit(true)}>Đăng nhập bằng Google</button>}
    <p><button disabled={busy || !hydrated} onClick={() => setMode(mode === "login" ? "signup" : "login")}>{mode === "login" ? "Tạo tài khoản" : "Đăng nhập"}</button> · <button disabled={busy || !hydrated} onClick={() => setMode("forgot")}>Quên mật khẩu</button></p>
    <Link href="/">Xem giao diện minh họa</Link>
  </div></section></div>;
}
