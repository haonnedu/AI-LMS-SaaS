"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@/lib/api/generated";
import { read } from "@/lib/client/api";
import { formatScore, scoreText } from "@/lib/client/assessment";
import { StudentShell } from "./student-shell";
import { useStudent } from "./use-student";
import styles from "./student.module.css";

type Result = components["schemas"]["StudentResultDTO"];

function summary(result: Result) {
  if (result.gradingStatus === "not_submitted" || result.status === "in_progress") return { title: "Bài chưa được nộp", text: "Bạn chưa nộp bài này.", score: false };
  if (result.gradingStatus === "void") return { title: "Bài làm đã bị hủy", text: "Bài làm này không được tính điểm.", score: false };
  if (result.scoreReleased && result.score !== null) return { title: "Điểm của bạn", text: "", score: true };
  if (result.gradingStatus === "pending") return { title: "Đã nộp bài", text: "Bài của bạn đang chờ chấm điểm.", score: false };
  return { title: "Đã nộp bài", text: "Điểm sẽ hiển thị khi giáo viên công bố.", score: false };
}

export function ResultsScreen({ attemptId }: { attemptId: string }) {
  const { ready, message, handle, reload } = useStudent();
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const epoch = useRef(0);
  const load = useCallback(async () => {
    const mine = ++epoch.current;
    setError("");
    try {
      const res: Result = await read(`/api/backend/student/attempts/${attemptId}/results`);
      if (mine === epoch.current) setResult(res);
    } catch (e) { if (mine === epoch.current) setError(handle(e)); }
  }, [attemptId, handle]);
  // Network synchronization once the session is ready.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { if (ready) void load(); }, [ready, load]);

  const head = result ? summary(result) : null;
  const items = result ? [...result.items].sort((a, b) => a.position - b.position) : [];
  return <StudentShell><div className={styles.content}>
    <Link href="/student/assignments" className={styles.muted} style={{ minHeight: 44, display: "inline-flex", alignItems: "center" }}>← Bài được giao</Link>
    {!ready && !message && <p role="status">Đang tải…</p>}
    {message && <div className={styles.card}><p role="alert" className={styles.error}>{message}</p><button className={styles.btn} onClick={() => void reload()}>Thử lại</button></div>}
    {error && <div className={styles.card}><p role="alert" className={styles.error}>{error}</p><button className={styles.btn} onClick={() => void load()}>Tải lại</button></div>}
    {result && head && <section className={styles.card} aria-live="polite">
      <h1>{head.title}</h1>
      {head.score ? <p><span className={styles.big}>{scoreText(result.score, result.maxScore)}</span> điểm</p> : <p className={styles.muted}>{head.text}</p>}
      {result.status === "in_progress" && <Link className={styles.btn} data-primary="true" href={`/student/attempts/${attemptId}`}>Tiếp tục làm bài</Link>}
    </section>}
    {result && result.status !== "in_progress" && items.length > 0 && <section className={styles.group} aria-label="Chi tiết từng câu">
      <h2>Chi tiết từng câu</h2>
      {!result.solutionsReleased && <p className={styles.muted}>Đáp án sẽ hiển thị khi giáo viên công bố.</p>}
      <ul className={styles.list}>{items.map(item => <li key={item.itemId} className={styles.resultItem}>
        <strong>Câu {item.position}</strong>
        <span>Bạn chọn: {item.selectedKey ?? "Bỏ trống"}</span>
        {result.scoreReleased && item.awardedPoints !== null && <span>Điểm: {formatScore(item.awardedPoints)} / {formatScore(item.maxPoints)}</span>}
        {result.solutionsReleased && item.solution && <>
          {item.solution.correctKey && <span>Đáp án đúng: <strong>{item.solution.correctKey}</strong></span>}
          {item.solution.explanation && <span className={styles.muted}>{item.solution.explanation}</span>}
        </>}
      </li>)}</ul>
    </section>}
  </div></StudentShell>;
}
