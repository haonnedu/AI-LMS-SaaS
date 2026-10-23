"use client";
import Link from "next/link";
import { useState } from "react";
import { usePrivacyRequest } from "@/components/privacy/use-privacy-request";
import { isRequestTerminal, requestStatusText, safeDownloadUrl } from "@/lib/client/privacy";
import { StudentDialog } from "./student-dialog";
import { StudentShell } from "./student-shell";
import { useStudent } from "./use-student";
import styles from "./student.module.css";

const poll = (id: string) => `/api/backend/student/me/privacy-requests/${id}`;
const fmt = (value: string) => new Date(value).toLocaleString("vi-VN");

export function StudentPrivacyScreen() {
  const { csrf, ready, message, handle, reload } = useStudent();
  const exporter = usePrivacyRequest({ createUrl: "/api/backend/student/me/privacy-requests", pollUrl: poll, csrf, handle });
  const eraser = usePrivacyRequest({ createUrl: "/api/backend/student/me/privacy-requests", pollUrl: poll, csrf, handle });
  const [confirming, setConfirming] = useState(false);
  const link = safeDownloadUrl(exporter.request?.downloadUrl);
  const exportRunning = exporter.busy || (exporter.request !== null && !link && !isRequestTerminal(exporter.request.status) && !exporter.gaveUp);

  async function erase() {
    setConfirming(false);
    await eraser.start("erasure");
  }
  return <StudentShell><div className={styles.content}>
    <h1 style={{ fontSize: 24 }}>Dữ liệu của em</h1>
    {!ready && !message && <p role="status">Đang tải…</p>}
    {message && <div className={styles.card}><p role="alert" className={styles.error}>{message}</p><button className={styles.btn} onClick={() => void reload()}>Thử lại</button></div>}
    {ready && <>
      <section className={styles.card} aria-labelledby="export-title">
        <h2 id="export-title">Tải bản sao dữ liệu</h2>
        <p>Em có thể tải về bản sao thông tin và bài làm của em trên Eduvia. Việc chuẩn bị có thể mất một lúc.</p>
        <button className={styles.btn} data-primary="true" disabled={!csrf || exportRunning} onClick={() => void exporter.start("export")}>{exportRunning ? "Đang chuẩn bị…" : "Tải bản sao dữ liệu"}</button>
        <div role="status" aria-live="polite">
          {exporter.request && !link && <p>{exporter.gaveUp ? "Việc này đang lâu hơn bình thường. Em hãy quay lại sau ít phút." : requestStatusText("export", exporter.request.status)}</p>}
          {link && <p><a className={styles.link} href={link} rel="noreferrer" download>Tải bản sao dữ liệu của em</a>{exporter.request?.downloadExpiresAt ? <span className={styles.muted}> (dùng được đến {fmt(exporter.request.downloadExpiresAt)})</span> : null}</p>}
        </div>
        {exporter.error && <p role="alert" className={styles.error}>{exporter.error}</p>}
      </section>
      <section className={styles.card} aria-labelledby="erase-title">
        <h2 id="erase-title">Yêu cầu xóa tài khoản</h2>
        <p>Nếu em không muốn dùng Eduvia nữa, em có thể xin xóa dữ liệu của mình.</p>
        <button className={styles.btn} disabled={!csrf || eraser.busy || eraser.request !== null} onClick={() => setConfirming(true)}>Yêu cầu xóa tài khoản</button>
        <div role="status" aria-live="polite">{eraser.request && <p>{eraser.gaveUp ? "Yêu cầu đã được ghi nhận và đang được xử lý." : requestStatusText("erasure", eraser.request.status)}</p>}</div>
        {eraser.error && <p role="alert" className={styles.error}>{eraser.error}</p>}
      </section>
      <p className={styles.muted}>Muốn biết thêm? Đọc <Link href="/privacy" className={styles.link}>Thông báo quyền riêng tư</Link>.</p>
    </>}
    {confirming && <StudentDialog title="Xóa tài khoản của em?" onClose={() => setConfirming(false)}>
      <p>Nếu em xác nhận:</p>
      <ul style={{ margin: "0 0 12px", paddingLeft: 20, display: "grid", gap: 6 }}>
        <li>Tên và email của em sẽ bị xóa hoặc ẩn đi.</li>
        <li>Em không đăng nhập hay vào lớp học được nữa.</li>
        <li>Bài làm và điểm của em có thể bị xóa. Việc này không hoàn tác được.</li>
      </ul>
      <p>Nếu chỉ cần giữ bản sao, em hãy tải dữ liệu trước.</p>
      <div className={styles.row}>
        <button className={styles.btn} data-primary="true" onClick={() => void erase()}>Tôi muốn xóa</button>
        <button className={styles.btn} autoFocus onClick={() => setConfirming(false)}>Không, giữ lại</button>
      </div>
    </StudentDialog>}
  </div></StudentShell>;
}
