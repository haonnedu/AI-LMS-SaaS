"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@/lib/api/generated";
import { read, RequestError } from "@/lib/client/api";
import {
  ackSave, adoptServer, beginSave, failedCount, failSave, formatCountdown, getIdempotencyKey, initItem, isAttemptOver, isRetryableStatus,
  remainingMs, retryDelay, saveLabel, selectAnswer, timerPhase, unansweredCount, unsavedCount, type ItemSave,
} from "@/lib/client/assessment";
import { StudentDialog } from "./student-dialog";
import { StudentShell } from "./student-shell";
import { sessionKeys, useServerClock, useStudent } from "./use-student";
import styles from "./student.module.css";

type Attempt = components["schemas"]["AttemptDTO"];
type Saves = Record<string, ItemSave>;
const OVER_MESSAGE = "Hết giờ – bài đã được nộp theo hạn.";

export function QuizScreen({ attemptId }: { attemptId: string }) {
  const router = useRouter();
  const { csrf, ready, message, handle, reload } = useStudent();
  const { offset, now, sync } = useServerClock(1000);
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [saves, setSaves] = useState<Saves>({});
  const [index, setIndex] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [offline, setOffline] = useState(false);
  const [over, setOver] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [note, setNote] = useState("");
  const savesRef = useRef<Saves>({});
  const retries = useRef<Record<string, number>>({});
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const csrfRef = useRef("");
  const base = `/api/backend/student/attempts/${attemptId}`;
  useEffect(() => { csrfRef.current = csrf; }, [csrf]);

  const commit = useCallback((itemId: string, next: ItemSave) => {
    savesRef.current = { ...savesRef.current, [itemId]: next };
    setSaves(savesRef.current);
  }, []);

  const fetchAttempt = useCallback(async () => {
    const res: Attempt = await read(base);
    sync(res.serverNow);
    return res;
  }, [base, sync]);

  // Initial load once the session is ready.
  useEffect(() => {
    if (!ready) return;
    let live = true;
    fetchAttempt().then(res => {
      if (!live) return;
      if (res.status !== "in_progress") { router.replace(`/student/attempts/${attemptId}/results`); return; }
      const items = [...res.items].sort((a, b) => a.position - b.position);
      savesRef.current = Object.fromEntries(items.map(item => [item.itemId, initItem(item)]));
      setSaves(savesRef.current);
      setAttempt({ ...res, items });
    }, (e: unknown) => { if (live) setLoadError(handle(e)); });
    return () => { live = false; };
  }, [ready, fetchAttempt, handle, router, attemptId]);

  // A 409 stale_answer: refetch and show the server value for that item.
  const adopt = useCallback(async (itemId: string) => {
    try {
      const fresh = await fetchAttempt();
      if (fresh.status !== "in_progress") { setOver(true); return; }
      const serverItem = fresh.items.find(item => item.itemId === itemId);
      const current = savesRef.current[itemId];
      if (serverItem && current) {
        commit(itemId, adoptServer(current, serverItem));
        setNote(`Câu ${serverItem.position} đã được cập nhật theo dữ liệu mới nhất từ máy chủ.`);
      }
    } catch (e) {
      const current = savesRef.current[itemId];
      if (current) commit(itemId, failSave(current));
      if (!(e instanceof RequestError)) setOffline(true);
    }
  }, [fetchAttempt, commit]);

  /** Sends the pending answer of one item (single flight per item) and chains follow-up saves. */
  const pump = useCallback(async function run(itemId: string): Promise<void> {
    clearTimeout(timers.current[itemId]);
    const current = savesRef.current[itemId];
    const begun = current ? beginSave(current) : null;
    if (!begun) return;
    commit(itemId, begun.state);
    try {
      const res: { answerRevision: number; serverNow: string } = await read(`${base}/answers/${itemId}`, {
        method: "PUT",
        headers: { "X-CSRF-Token": csrfRef.current, "Content-Type": "application/json" },
        body: JSON.stringify(begun.request),
      });
      sync(res.serverNow);
      retries.current[itemId] = 0;
      setOffline(false);
      commit(itemId, ackSave(savesRef.current[itemId], begun.request, res.answerRevision));
      void run(itemId);
    } catch (e) {
      const status = e instanceof RequestError ? e.status : null;
      if (e instanceof RequestError && e.code === "stale_answer") { await adopt(itemId); return; }
      commit(itemId, failSave(savesRef.current[itemId]));
      if (e instanceof RequestError && isAttemptOver(e.code)) { setOver(true); return; }
      if (status === 401) { handle(e); return; }
      if (status === null) setOffline(true);
      if (isRetryableStatus(status)) {
        const attemptNo = retries.current[itemId] ?? 0;
        retries.current[itemId] = attemptNo + 1;
        timers.current[itemId] = setTimeout(() => void run(itemId), retryDelay(attemptNo));
      }
    }
  }, [base, commit, sync, adopt, handle]);

  function choose(itemId: string, key: string | null) {
    const current = savesRef.current[itemId];
    if (!current) return;
    commit(itemId, selectAnswer(current, key));
    void pump(itemId);
  }
  const retryAll = useCallback(() => { for (const id of Object.keys(savesRef.current)) void pump(id); }, [pump]);

  // Reconnect handling: keep local state, show a banner, and flush as soon as the network is back.
  useEffect(() => {
    const online = () => { setOffline(false); retryAll(); };
    const offlineEvent = () => setOffline(true);
    window.addEventListener("online", online);
    window.addEventListener("offline", offlineEvent);
    const pending = timers.current;
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offlineEvent);
      for (const timer of Object.values(pending)) clearTimeout(timer);
    };
  }, [retryAll]);

  const items = attempt?.items ?? [];
  const states = items.map(item => saves[item.itemId]).filter((state): state is ItemSave => !!state);
  const unanswered = unansweredCount(states);
  const unsaved = unsavedCount(states);
  const failed = failedCount(states);
  const saving = unsaved - failed;

  // Warn before leaving the page while answers are still unsaved.
  useEffect(() => {
    if (unsaved === 0) return;
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [unsaved]);

  // Once the deadline passed or the server closed the attempt, send the student to the results.
  useEffect(() => {
    if (!over) return;
    const id = setTimeout(() => router.replace(`/student/attempts/${attemptId}/results`), 3000);
    return () => clearTimeout(id);
  }, [over, router, attemptId]);

  async function submit() {
    setSubmitting(true); setSubmitError("");
    // One key per attempt: a retry after a lost response replays the same submission.
    const key = getIdempotencyKey(sessionKeys(), "submit", attemptId);
    try {
      await read(`${base}/submit`, { method: "POST", headers: { "X-CSRF-Token": csrf, "Idempotency-Key": key } });
      router.replace(`/student/attempts/${attemptId}/results`);
    } catch (e) {
      if (e instanceof RequestError && isAttemptOver(e.code)) { setConfirming(false); setOver(true); }
      else setSubmitError(handle(e));
      setSubmitting(false);
    }
  }

  const remaining = attempt?.deadlineAt ? remainingMs(attempt.deadlineAt, offset, now) : null;
  const phase = timerPhase(remaining);
  const expired = phase === "expired";
  const current = items[Math.min(index, Math.max(0, items.length - 1))];
  const currentState = current ? saves[current.itemId] : undefined;
  const announcement = phase === "warning" ? "Còn dưới 2 phút." : expired ? "Đã hết giờ." : "";

  if (over) return <StudentShell nav={false}><div className={styles.content}>
    <section className={styles.card}><h1 role="status">{OVER_MESSAGE}</h1><p className={styles.muted}>Đang chuyển đến kết quả…</p>
      <Link className={styles.btn} data-primary="true" href={`/student/attempts/${attemptId}/results`}>Xem kết quả</Link></section>
  </div></StudentShell>;

  return <StudentShell nav={false}>
    {attempt && <div className={styles.quizBar}>
      <strong>{attempt.title}</strong>
      {remaining !== null && <span className={styles.timer} data-phase={phase} role="timer" aria-label="Thời gian còn lại">{formatCountdown(remaining)}</span>}
    </div>}
    <p className="sr-only" role="status" aria-live="polite">{announcement}</p>
    <div className={styles.content}>
      {!ready && !message && <p role="status">Đang tải bài làm…</p>}
      {message && <div className={styles.card}><p role="alert" className={styles.error}>{message}</p><button className={styles.btn} onClick={() => void reload()}>Thử lại</button></div>}
      {loadError && <div className={styles.card}><p role="alert" className={styles.error}>{loadError}</p><button className={styles.btn} onClick={() => window.location.reload()}>Tải lại trang</button></div>}
      {offline && <p className={styles.banner} role="status">Mất kết nối. Các câu trả lời vẫn được giữ trên máy này và sẽ tự lưu lại khi có mạng. <button className={styles.btn} style={{ minHeight: 40, marginTop: 8 }} onClick={retryAll}>Thử lại ngay</button></p>}
      {phase === "warning" && <p className={styles.warnBanner}>Còn dưới 2 phút. Hãy kiểm tra lại và nộp bài.</p>}
      {note && <p className={styles.notice} role="status">{note}</p>}
      {attempt && items.length === 0 && <div className={styles.card}><p className={styles.muted}>Bài này chưa có câu hỏi.</p></div>}
      {attempt && items.length > 0 && <>
        <nav aria-label="Danh sách câu hỏi"><ul className={styles.nav}>{items.map((item, i) => {
          const state = saves[item.itemId];
          return <li key={item.itemId}><button type="button" className={styles.navBtn} data-answered={state?.desiredKey ? "true" : "false"} data-unsaved={state && state.status !== "saved" ? "true" : "false"}
            aria-current={current?.itemId === item.itemId ? "step" : undefined}
            aria-label={`Câu ${i + 1}${state?.desiredKey ? ", đã trả lời" : ", chưa trả lời"}${state && state.status !== "saved" ? ", chưa lưu" : ""}`}
            onClick={() => setIndex(i)}>{i + 1}</button></li>;
        })}</ul></nav>
        {current && currentState && <section className={styles.card}>
          <fieldset className={styles.question}>
            <legend><span className={styles.qMeta}>Câu {items.indexOf(current) + 1}/{items.length} · {current.points} điểm</span>{current.stem}</legend>
            {current.choices.map(choice => <label key={choice.key} className={styles.choice}>
              <input type="radio" name={`q-${current.itemId}`} value={choice.key} checked={currentState.desiredKey === choice.key} onChange={() => choose(current.itemId, choice.key)} />
              <span><strong>{choice.key}.</strong> {choice.text}</span>
            </label>)}
          </fieldset>
          <p className={styles.saveState} data-status={currentState.status} role="status" aria-live="polite">
            {saveLabel(currentState)}
            {currentState.status === "error" && <> <button type="button" className={styles.btn} style={{ minHeight: 40, marginLeft: 8 }} onClick={() => void pump(current.itemId)}>Thử lại</button></>}
          </p>
          {currentState.desiredKey && <button type="button" className={styles.btn} onClick={() => choose(current.itemId, null)}>Bỏ chọn</button>}
        </section>}
      </>}
    </div>
    {attempt && items.length > 0 && <div className={styles.pager}>
      <button type="button" className={styles.btn} disabled={index <= 0} onClick={() => setIndex(i => Math.max(0, i - 1))}>Câu trước</button>
      <button type="button" className={styles.btn} disabled={index >= items.length - 1} onClick={() => setIndex(i => Math.min(items.length - 1, i + 1))}>Câu sau</button>
      <button type="button" className={`${styles.btn} ${styles.span2}`} data-primary="true" onClick={() => { setSubmitError(""); setConfirming(true); }}>Nộp bài</button>
    </div>}
    {attempt && (confirming || expired) && <StudentDialog title={expired ? "Hết giờ làm bài" : "Nộp bài?"} onClose={expired ? undefined : () => setConfirming(false)}>
      {expired ? <p>Đã hết thời gian làm bài. Hãy nộp bài để ghi nhận các câu bạn đã trả lời.</p>
        : <p>{unanswered > 0 ? `Bạn còn ${unanswered} câu chưa trả lời.` : "Bạn đã trả lời tất cả các câu."} Sau khi nộp bạn không thể sửa bài.</p>}
      {saving > 0 && <p className={styles.muted} role="status">Đang lưu {saving} câu trả lời…</p>}
      {failed > 0 && <p className={styles.warnBanner} role="alert">{failed} câu chưa lưu được. <button type="button" className={styles.btn} style={{ minHeight: 40 }} onClick={retryAll}>Thử lưu lại</button></p>}
      {submitError && <p role="alert" className={styles.error}>{submitError}</p>}
      <div className={styles.row}>
        <button type="button" className={styles.btn} data-primary="true" disabled={submitting || (!expired && saving > 0)} onClick={() => void submit()}>{submitting ? "Đang nộp…" : submitError ? "Thử nộp lại" : failed > 0 ? "Vẫn nộp bài" : "Nộp bài"}</button>
        {!expired && <button type="button" className={styles.btn} disabled={submitting} onClick={() => setConfirming(false)}>Tiếp tục làm bài</button>}
      </div>
    </StudentDialog>}
  </StudentShell>;
}
