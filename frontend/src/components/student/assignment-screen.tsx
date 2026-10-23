"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@/lib/api/generated";
import { read, RequestError } from "@/lib/client/api";
import { AVAILABILITY_LABEL, AVAILABILITY_TONE, canStart, clearIdempotencyKey, formatDuration, getIdempotencyKey, isRetryableStatus, startLabel, windowHint } from "@/lib/client/assessment";
import { CONSENT_REQUIRED_MESSAGE } from "@/lib/client/privacy";
import { ConsentRequiredCard } from "./consent-gate";
import { StudentShell } from "./student-shell";
import { sessionKeys, useServerClock, useStudent } from "./use-student";
import styles from "./student.module.css";

type Detail = components["schemas"]["StudentAssignmentDetailDTO"];
type Started = components["schemas"]["StartedAttemptDTO"];
const fmt = (value: string) => new Date(value).toLocaleString("vi-VN");

export function StudentAssignmentScreen({ assignmentId }: { assignmentId: string }) {
  const router = useRouter();
  const { csrf, ready, message, handle, reload } = useStudent();
  const { offset, now, sync } = useServerClock(1000);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const [consentBlocked, setConsentBlocked] = useState(false);
  const epoch = useRef(0);

  const load = useCallback(async () => {
    const mine = ++epoch.current;
    setError("");
    try {
      const res: Detail = await read(`/api/backend/student/assignments/${assignmentId}`);
      if (mine !== epoch.current) return;
      setDetail(res); sync(res.serverNow);
    } catch (e) { if (mine === epoch.current) setError(handle(e)); }
  }, [assignmentId, handle, sync]);
  // Network synchronization once the session is ready.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { if (ready) void load(); }, [ready, load]);

  async function start() {
    setStarting(true); setError(""); setConsentBlocked(false);
    // The same key is reused by every retry for this assignment until the server answers definitively.
    const key = getIdempotencyKey(sessionKeys(), "start", assignmentId);
    try {
      const started: Started = await read(`/api/backend/student/assignments/${assignmentId}/attempts`, { method: "POST", headers: { "X-CSRF-Token": csrf, "Idempotency-Key": key } });
      clearIdempotencyKey(sessionKeys(), "start", assignmentId);
      router.push(`/student/attempts/${started.attemptId}`);
    } catch (e) {
      if (e instanceof RequestError && !isRetryableStatus(e.status)) clearIdempotencyKey(sessionKeys(), "start", assignmentId);
      if (e instanceof RequestError && e.status === 403 && e.code === "consent_required") { setConsentBlocked(true); setError(CONSENT_REQUIRED_MESSAGE); }
      else setError(handle(e));
      setStarting(false);
      void load();
    }
  }

  return <StudentShell><div className={styles.content}>
    <Link href="/student/assignments" className={styles.muted} style={{ minHeight: 44, display: "inline-flex", alignItems: "center" }}>← Bài được giao</Link>
    {!ready && !message && <p role="status">Đang tải…</p>}
    {message && <div className={styles.card}><p role="alert" className={styles.error}>{message}</p><button className={styles.btn} onClick={() => void reload()}>Thử lại</button></div>}
    {detail && <section className={styles.card}>
      <h1>{detail.title}</h1>
      <p className={styles.muted}>{detail.className}</p>
      <div className={styles.meta}>
        <span className={styles.chip} data-tone={AVAILABILITY_TONE[detail.availability]}>{AVAILABILITY_LABEL[detail.availability]}</span>
        <span>{windowHint(detail.opensAt, detail.closesAt, offset, now)}</span>
      </div>
      <dl style={{ margin: 0, display: "grid", gap: 6 }}>
        <div><dt className={styles.muted}>Mở lúc</dt><dd style={{ margin: 0 }}>{fmt(detail.opensAt)}</dd></div>
        <div><dt className={styles.muted}>Đóng lúc</dt><dd style={{ margin: 0 }}>{detail.closesAt ? fmt(detail.closesAt) : "Không giới hạn"}</dd></div>
        <div><dt className={styles.muted}>Thời gian làm bài</dt><dd style={{ margin: 0 }}>{formatDuration(detail.timeLimitSeconds)}</dd></div>
        <div><dt className={styles.muted}>Số câu hỏi</dt><dd style={{ margin: 0 }}>{detail.itemCount}{detail.totalPoints ? ` câu · ${detail.totalPoints} điểm` : " câu"}</dd></div>
        <div><dt className={styles.muted}>Số lần làm</dt><dd style={{ margin: 0 }}>{detail.attemptsUsed}/{detail.maxAttempts}</dd></div>
      </dl>
      {detail.instructions && <div><h2>Hướng dẫn</h2><p style={{ whiteSpace: "pre-wrap" }}>{detail.instructions}</p></div>}
      {error && !consentBlocked && <p role="alert" className={styles.error}>{error}</p>}
      {consentBlocked && <ConsentRequiredCard />}
      {detail.availability === "resume" && detail.inProgressAttemptId && <Link className={styles.btn} data-primary="true" href={`/student/attempts/${detail.inProgressAttemptId}`}>Tiếp tục</Link>}
      {detail.availability === "open" && <button className={styles.btn} data-primary="true" disabled={starting} onClick={() => void start()}>{starting ? "Đang bắt đầu…" : startLabel("open")}</button>}
      {detail.availability === "resume" && !detail.inProgressAttemptId && canStart("resume") && <button className={styles.btn} data-primary="true" disabled={starting} onClick={() => void start()}>{starting ? "Đang mở bài…" : "Tiếp tục"}</button>}
      {detail.availability === "not_open_yet" && <p className={styles.muted}>Bài chưa mở. Hãy quay lại khi đến giờ.</p>}
      {detail.availability === "closed" && <p className={styles.muted}>Bài đã đóng.</p>}
      {detail.availability === "limit_reached" && <p className={styles.muted}>Bạn đã dùng hết số lần làm bài.</p>}
      {detail.latestAttemptId && detail.latestAttemptStatus !== "in_progress" && <Link className={styles.btn} href={`/student/attempts/${detail.latestAttemptId}/results`}>Xem kết quả</Link>}
    </section>}
    {error && !detail && !consentBlocked && <div className={styles.card}><p role="alert" className={styles.error}>{error}</p><button className={styles.btn} onClick={() => void load()}>Tải lại</button></div>}
  </div></StudentShell>;
}
