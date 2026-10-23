"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "@/lib/api/generated";
import { read } from "@/lib/client/api";
import { AVAILABILITY_GROUP, AVAILABILITY_LABEL, AVAILABILITY_TONE, canStart, formatDuration, groupByAvailability, startLabel, windowHint } from "@/lib/client/assessment";
import { StudentShell } from "./student-shell";
import { useServerClock, useStudent } from "./use-student";
import { ConsentGate } from "./consent-gate";
import styles from "./student.module.css";

type Item = components["schemas"]["StudentAssignmentDTO"];

export function StudentAssignmentsScreen() {
  const { csrf, ready, message, handle, reload } = useStudent();
  const { offset, now, sync } = useServerClock(15000);
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [needsYear, setNeedsYear] = useState(false);
  const epoch = useRef(0);

  const load = useCallback(async () => {
    const mine = ++epoch.current;
    setLoading(true); setError("");
    try {
      const res: { items: Item[] } = await read("/api/backend/student/assignments");
      if (mine !== epoch.current) return;
      setItems(res.items); sync(res.items[0]?.serverNow);
    } catch (e) { if (mine === epoch.current) setError(handle(e)); }
    finally { if (mine === epoch.current) setLoading(false); }
  }, [handle, sync]);
  // Network synchronization once the session is ready.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { if (ready) void load(); }, [ready, load]);

  return <StudentShell><div className={styles.content}>
    <h1 style={{ fontSize: 24 }}>Bài được giao</h1>
    {ready && <ConsentGate csrf={csrf} onPending={setNeedsYear} />}
    {!ready && !message && <p role="status">Đang tải…</p>}
    {message && <div className={styles.card}><p role="alert" className={styles.error}>{message}</p><button className={styles.btn} onClick={() => void reload()}>Thử lại</button></div>}
    {error && <div className={styles.card}><p role="alert" className={styles.error}>{error}</p><button className={styles.btn} onClick={() => void load()}>Tải lại</button></div>}
    {loading && !items && !error && <p role="status">Đang tải bài được giao…</p>}
    {items && needsYear && <p className={styles.muted}>Em hãy chọn năm sinh ở trên để xem bài được giao.</p>}
    {items && !needsYear && items.length === 0 && <div className={styles.card}><p className={styles.muted}>Bạn chưa có bài nào được giao. Khi giáo viên giao bài, bài sẽ xuất hiện ở đây.</p></div>}
    {items && !needsYear && groupByAvailability(items).map(group => <section key={group.availability} className={styles.group} aria-label={AVAILABILITY_GROUP[group.availability]}>
      <h2>{AVAILABILITY_GROUP[group.availability]} ({group.items.length})</h2>
      <ul className={styles.list}>{group.items.map(item => <li key={item.id} className={styles.card}>
        <div><strong>{item.title}</strong><p className={styles.muted}>{item.className}</p></div>
        <div className={styles.meta}>
          <span className={styles.chip} data-tone={AVAILABILITY_TONE[item.availability]}>{AVAILABILITY_LABEL[item.availability]}</span>
          <span>{windowHint(item.opensAt, item.closesAt, offset, now)}</span>
          <span>{formatDuration(item.timeLimitSeconds)}</span>
          <span>Đã làm {item.attemptsUsed}/{item.maxAttempts} lần</span>
        </div>
        <Link className={styles.btn} data-primary={canStart(item.availability) ? "true" : undefined} href={`/student/assignments/${item.id}`}>
          {canStart(item.availability) ? startLabel(item.availability) : item.availability === "done" ? "Xem chi tiết" : "Xem thông tin"}
        </Link>
      </li>)}</ul>
    </section>)}
  </div></StudentShell>;
}
