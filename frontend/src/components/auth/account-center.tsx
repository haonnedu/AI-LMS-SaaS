"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import styles from "../workspace/workspace.module.css";
import formStyles from "./mock-auth.module.css";

type Account = { user: { id: string | null; name: string; email: string }; methods: { password: boolean; google: boolean }; googleEnabled: boolean };
export function AccountCenter() {
  const [account, setAccount] = useState<Account | null>(null), [csrf, setCsrf] = useState("");
  const [password, setPassword] = useState(""), [message, setMessage] = useState(""), [busy, setBusy] = useState(false), [confirm, setConfirm] = useState(false);
  useEffect(() => {
    let active = true;
    Promise.all([fetch("/api/account", { cache: "no-store" }).then(r => r.ok ? r.json() : Promise.reject()), fetch("/api/session", { cache: "no-store" }).then(r => r.json())]).then(([info, session]) => {
      if (!active) return;
      if (!session.authenticated) { window.location.replace("/login"); return; }
      setAccount(info); setCsrf(session.csrfToken);
      const query = new URLSearchParams(window.location.search);
      setConfirm(query.get("confirm") === "google");
      if (query.has("error")) setMessage("Chưa thể liên kết Google. Hãy chọn cùng email, chưa thuộc tài khoản khác, rồi xác thực lại và thử lại.");
    }).catch(() => { if (active) setMessage("Không tải được tài khoản. Vui lòng tải lại trang."); });
    const channel = new BroadcastChannel("eduvia-auth");
    channel.onmessage = event => { if (event.data === "logout") window.location.replace("/login"); };
    const restore = (event: PageTransitionEvent) => { if (event.persisted) window.location.reload(); };
    window.addEventListener("pageshow", restore);
    return () => { active = false; channel.close(); window.removeEventListener("pageshow", restore); };
  }, []);
  async function action(name: string) {
    setBusy(true); setMessage("");
    try {
      const response = await fetch("/api/account/" + name, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify(name === "reauthenticate" ? { password } : {}) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || "Không thể hoàn thành thao tác.");
      if (result.redirect === "/login") {
        const channel = new BroadcastChannel("eduvia-auth"); channel.postMessage("logout"); channel.close(); window.location.assign(new URL("/login", window.location.origin).href);
      } else if (result.url) {
        const url = new URL(result.url); if (url.protocol !== "https:") throw new Error("Đường dẫn không hợp lệ."); window.location.assign(url.href);
      } else { setPassword(""); setMessage(name === "reauthenticate" ? "Đã xác thực lại. Bạn có thể liên kết hoặc hủy Google trong 5 phút." : "Đã gửi hướng dẫn đến email của bạn."); }
    } catch (error) { setMessage(error instanceof Error ? error.message : "Dịch vụ tạm thời không khả dụng."); }
    finally { setBusy(false); }
  }
  return <main className={styles.page}><section className={styles.card}><h1>Trung tâm tài khoản</h1>
    {account && <><p>{account.user.email}</p><p>Mã tài khoản: {account.user.id || "Chưa mở workspace"}</p>
      <p>Email và mật khẩu: {account.methods.password ? "Đã thiết lập" : "Chưa thiết lập"}</p>
      <button disabled={busy} onClick={() => void action("password")}>{account.methods.password ? "Đặt lại mật khẩu qua email" : "Thiết lập mật khẩu qua email"}</button>
      <p>Google: {account.methods.google ? "Đã liên kết" : "Chưa liên kết"}</p>
      {account.methods.password && <form className={formStyles.fields} onSubmit={event => { event.preventDefault(); void action("reauthenticate"); }}><label>Xác thực lại bằng mật khẩu<input required type="password" autoComplete="current-password" maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /></label><button disabled={busy}>Xác thực lại</button></form>}
      {confirm ? <><p>Google vừa được xác thực và có cùng email. Xác nhận để dùng Google đăng nhập vào tài khoản Eduvia này. Các phiên sẽ kết thúc sau khi liên kết.</p><button disabled={busy} onClick={() => void action("confirm-google")}>Xác nhận liên kết Google</button><Link href="/account">Hủy</Link></> : account.methods.google ? <button disabled={busy || !account.methods.password} onClick={() => void action("unlink-google")}>Hủy liên kết Google và đăng xuất</button> : <button disabled={busy || !account.googleEnabled || !account.methods.password} onClick={() => void action("link-google")}>Liên kết Google</button>}
      {!account.methods.password && <p>Thiết lập mật khẩu qua email trước khi thay đổi phương thức đăng nhập.</p>}
    </>}
    {message && <p role="status">{message}</p>}<p><Link href="/dashboard">Về workspace</Link></p>
  </section></main>;
}
