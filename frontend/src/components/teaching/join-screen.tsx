"use client";
import Link from "next/link";
import { useState } from "react";
import type { components } from "@/lib/api/generated";
import { jsonInit, read, RequestError } from "@/lib/client/api";
import { useRouter } from "next/navigation";
import { ConsentGate } from "@/components/student/consent-gate";
import styles from "./teaching.module.css";

type Accepted = components["schemas"]["InvitationAcceptedDTO"];
const ERRORS: Record<number, string> = {
  404: "Mã mời không hợp lệ.",
  410: "Mã mời đã hết hạn hoặc đã bị thu hồi.",
  409: "Bạn đã tham gia lớp này hoặc mã mời đã hết lượt dùng.",
  429: "Bạn thử quá nhiều lần. Vui lòng thử lại sau.",
};
export function JoinScreen({ token }: { token: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<Accepted | null>(null);
  const [csrf, setCsrf] = useState("");
  async function accept() {
    setBusy(true); setError("");
    try {
      const session = await read("/api/session");
      if (!session.authenticated || !session.csrfToken) { router.replace("/login?returnTo=" + encodeURIComponent("/join/" + token)); return; }
      setCsrf(session.csrfToken);
      setDone(await read(`/api/backend/invitations/${token}/accept`, jsonInit(session.csrfToken)));
    } catch (e) {
      if (e instanceof RequestError && e.status === 401) { router.replace("/login?returnTo=" + encodeURIComponent("/join/" + token)); return; }
      if (e instanceof RequestError && e.code === "onboarding_required") { router.replace("/onboarding"); return; }
      setError(e instanceof RequestError ? ERRORS[e.status] || e.message : "Không thể kết nối. Vui lòng thử lại.");
    } finally { setBusy(false); }
  }
  return <div className={styles.page}><div className={styles.wrap}><section className={styles.card} aria-busy={busy}>
    <h1>Tham gia lớp học</h1>
    {!done && <><p>Bạn được mời tham gia một lớp trên Eduvia. Nhấn nút bên dưới để xác nhận tham gia.</p>
      <div className={styles.actions}><button className="button button-primary" disabled={busy} onClick={() => void accept()}>{busy ? "Đang xử lý…" : "Tham gia lớp"}</button></div></>}
    {done && <><p role="status" aria-live="polite">Bạn đã tham gia lớp <strong>{done.className}</strong>.</p><ConsentGate csrf={csrf} /><div className={styles.actions}><Link className="button button-primary" href="/student/assignments">Xem bài được giao</Link><Link className="button button-secondary" href="/dashboard">Về trang chính</Link></div></>}
    {error && <p role="alert" className={styles.error}>{error}</p>}
  </section></div></div>;
}
