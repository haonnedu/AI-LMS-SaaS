"use client";
import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
const subscribe = () => () => {};
export function MigrationScreen() {
  const hydrated = useSyncExternalStore(subscribe, () => true, () => false);
  const [message, setMessage] = useState(""), [busy, setBusy] = useState(false);
  async function transfer() {
    setBusy(true);
    try {
      const session = await (await fetch("/api/session", { cache: "no-store" })).json();
      const response = await fetch("/api/account/migrate", { method: "POST", headers: { "X-CSRF-Token": session.csrfToken } });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || "Chưa chuyển được tài khoản.");
      window.location.assign(result.redirect);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Dịch vụ tạm thời không khả dụng."); }
    finally { setBusy(false); }
  }
  return <main><h1>Giữ lại workspace từ tài khoản cũ</h1><p>Dùng cùng email đã xác minh ở cả hai hệ thống. Chưa bấm mở workspace mới trước khi chuyển đổi.</p>
    <p><a href="/auth/login?migration=1">1. Xác thực lại tài khoản Auth0 cũ</a></p>
    <button disabled={busy || !hydrated} onClick={() => void transfer()}>2. Xác nhận chuyển và đăng xuất</button>
    {message && <p role="status">{message}</p>}<p><Link href="/onboarding">Về onboarding</Link></p></main>;
}
