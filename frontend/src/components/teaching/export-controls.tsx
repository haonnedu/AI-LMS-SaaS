"use client";
import { useEffect, useRef, useState } from "react";
import type { components } from "@/lib/api/generated";
import { jsonInit, read, RequestError } from "@/lib/client/api";
import { nextDelay } from "@/lib/client/jobs";
import { AUDIENCE_LABEL, exportFailureMessage, exportFileName, expiryLabel, isExportTerminal, safeDownloadUrl, type Audience, type ExportFormat } from "@/lib/client/generation";
import styles from "./teaching.module.css";

type Accepted = components["schemas"]["ExportAcceptedDTO"];
type ExportJob = components["schemas"]["ExportJobDTO"];
export type ExportTarget = { contentRevisionId: string } | { examVersionId: string };
export type ExportCombo = { format: ExportFormat; audience: Audience };
type Entry = { phase: "working" | "done" | "failed"; message: string; url: string | null; expires: string | null; fileName: string };
const MAX_POLLS = 60;
const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

/** Requests an export, polls it, and shows a download link with expiry. Request bodies are never logged. */
export function ExportControls({ wsBase, csrf, target, title, combos, onError }: { wsBase: string; csrf: string; target: ExportTarget; title: string; combos: ExportCombo[]; onError: (e: unknown) => string }) {
  const [entries, setEntries] = useState<Record<string, Entry>>({});
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const keyOf = (combo: ExportCombo) => `${combo.format}-${combo.audience}`;
  const put = (key: string, entry: Entry) => { if (alive.current) setEntries(current => ({ ...current, [key]: entry })); };

  async function run(combo: ExportCombo) {
    const key = keyOf(combo);
    const fileName = exportFileName(title, combo.audience, combo.format);
    put(key, { phase: "working", message: "Đang tạo tệp…", url: null, expires: null, fileName });
    try {
      const accepted: Accepted = await read(`${wsBase}/exports`, jsonInit(csrf, { ...target, format: combo.format, audience: combo.audience }));
      let job: ExportJob = accepted.exportJob;
      let errors = 0;
      for (let i = 0; i < MAX_POLLS && !isExportTerminal(job); i++) {
        await sleep(nextDelay(errors));
        if (!alive.current) return;
        try { job = await read(`${wsBase}/exports/${job.id}`); errors = 0; }
        catch (e) { if (e instanceof RequestError && e.status === 401) { onError(e); return; } if (++errors >= 5) throw e; }
      }
      if (job.status === "succeeded") {
        const url = safeDownloadUrl(job.downloadUrl);
        put(key, url ? { phase: "done", message: "Tệp đã sẵn sàng.", url, expires: job.downloadExpiresAt ?? null, fileName } : { phase: "failed", message: "Tệp đã tạo nhưng chưa có liên kết tải. Hãy thử lại.", url: null, expires: null, fileName });
      } else if (job.status === "failed") put(key, { phase: "failed", message: exportFailureMessage(job.errorCode, combo.format), url: null, expires: null, fileName });
      else put(key, { phase: "failed", message: "Tệp chưa sẵn sàng sau thời gian chờ. Hãy thử lại sau.", url: null, expires: null, fileName });
    } catch (e) {
      const text = onError(e);
      const code = e instanceof RequestError ? e.code : undefined;
      put(key, { phase: "failed", message: combo.format === "pdf" ? exportFailureMessage(code, "pdf") : text, url: null, expires: null, fileName });
    }
  }
  return <div className={styles.exportBox}>
    <div className={styles.exportGrid} role="group" aria-label="Xuất tệp">
      {combos.map(combo => {
        const entry = entries[keyOf(combo)];
        return <button key={keyOf(combo)} type="button" className="button button-secondary" disabled={entry?.phase === "working"} onClick={() => void run(combo)}>
          {entry?.phase === "working" ? "Đang xuất…" : `${combo.format.toUpperCase()} · ${AUDIENCE_LABEL[combo.audience]}`}</button>;
      })}
    </div>
    <div aria-live="polite">
      {combos.map(combo => {
        const entry = entries[keyOf(combo)];
        if (!entry) return null;
        const label = `${combo.format.toUpperCase()} · ${AUDIENCE_LABEL[combo.audience]}`;
        return <p key={keyOf(combo)} className={`${styles.exportStatus} ${entry.phase === "failed" ? styles.error : ""}`} role={entry.phase === "failed" ? "alert" : "status"}>
          <strong>{label}: </strong>{entry.message}{" "}
          {entry.phase === "done" && entry.url && <><a href={entry.url} download={entry.fileName} rel="noopener noreferrer">Tải {entry.fileName}</a>{expiryLabel(entry.expires) && <small className={styles.muted}> · {expiryLabel(entry.expires)}</small>}</>}
        </p>;
      })}
    </div>
  </div>;
}
