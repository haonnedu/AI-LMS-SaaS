"use client";
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { read, RequestError } from "@/lib/client/api";
import { birthYearOptions, blockingConsents, isValidBirthYear, needsBirthYear } from "@/lib/client/privacy";
import type { StudentConsentItem, StudentConsentStatus } from "@/lib/client/privacy-types";
import styles from "./student.module.css";

/** Blocking explanation shown when a class needs a parent's consent. `classNames` is optional. */
export function ConsentRequiredCard({ classNames }: { classNames?: string[] }) {
  return <section className={styles.card} role="alert" aria-labelledby="consent-required-title">
    <h2 id="consent-required-title">Cần sự đồng ý của phụ huynh</h2>
    <p>Em chưa làm bài được vì chưa có sự đồng ý của phụ huynh{classNames && classNames.length > 0 ? <> cho lớp: <strong>{classNames.join(", ")}</strong></> : null}.</p>
    <p>Thầy cô hoặc nhà trường sẽ ghi nhận sự đồng ý này. Em hãy nhờ bố mẹ trao đổi với thầy cô nhé. Khi đã có, em quay lại đây làm bài như bình thường.</p>
    <p className={styles.muted}>Em có thể đọc cách Eduvia giữ dữ liệu của em ở <Link href="/privacy">trang Quyền riêng tư</Link>.</p>
  </section>;
}

function BirthYearCard({ csrf, onSaved }: { csrf: string; onSaved: (status: StudentConsentStatus) => void }) {
  const selectId = useId();
  const [year, setYear] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    const value = Number(year);
    if (!isValidBirthYear(value)) { setError("Em hãy chọn năm sinh của mình."); return; }
    setBusy(true); setError("");
    try {
      const saved: StudentConsentStatus = await read("/api/backend/student/me/birth-year", { method: "PUT", headers: { "X-CSRF-Token": csrf, "Content-Type": "application/json" }, body: JSON.stringify({ birthYear: value }) });
      onSaved(saved);
    } catch (e) { setError(e instanceof RequestError ? e.message : "Không thể kết nối. Em thử lại nhé."); }
    finally { setBusy(false); }
  }
  return <section className={styles.card} aria-labelledby={selectId + "-t"}>
    <h2 id={selectId + "-t"}>Năm sinh của em</h2>
    <p>Eduvia cần biết năm sinh của em để biết có cần hỏi ý kiến phụ huynh hay không. Em chỉ cần chọn một lần.</p>
    <form onSubmit={event => void submit(event)} style={{ display: "grid", gap: 12 }}>
      <label htmlFor={selectId} style={{ fontWeight: 650 }}>Em sinh năm nào?</label>
      <select id={selectId} className={styles.select} required value={year} onChange={event => setYear(event.target.value)} aria-invalid={error ? true : undefined} aria-describedby={error ? selectId + "-e" : undefined}>
        <option value="">Chọn năm sinh</option>
        {birthYearOptions().map(option => <option key={option} value={option}>{option}</option>)}
      </select>
      {error && <p id={selectId + "-e"} role="alert" className={styles.error}>{error}</p>}
      <button className={styles.btn} data-primary="true" type="submit" disabled={busy}>{busy ? "Đang lưu…" : "Lưu năm sinh"}</button>
    </form>
  </section>;
}

/**
 * Step 1: birth year when any class reports `unknown`. Step 2: blocking parent-consent card.
 * Renders nothing when everything is fine or the status endpoint is unavailable. Birth year is never logged or stored client-side.
 * `onPending(true)` tells a page the birth year is still missing so it can hide its list.
 */
export function ConsentGate({ csrf, onPending }: { csrf: string; onPending?: (pending: boolean) => void }) {
  const [items, setItems] = useState<StudentConsentItem[] | null>(null);
  const notify = useRef(onPending);
  useEffect(() => { notify.current = onPending; });
  const apply = useCallback((status: StudentConsentStatus) => { setItems(status.items); notify.current?.(needsBirthYear(status.items)); }, []);
  useEffect(() => {
    if (!csrf) return;
    let alive = true;
    read("/api/backend/student/me/consent-status")
      .then((status: StudentConsentStatus) => { if (alive && Array.isArray(status?.items)) apply(status); })
      .catch(() => { /* non-blocking: the server still enforces consent when an attempt starts */ });
    return () => { alive = false; };
  }, [csrf, apply]);
  if (!items) return null;
  if (needsBirthYear(items)) return <BirthYearCard csrf={csrf} onSaved={apply} />;
  const blocking = blockingConsents(items);
  return blocking.length ? <ConsentRequiredCard classNames={blocking.map(item => item.className)} /> : null;
}
