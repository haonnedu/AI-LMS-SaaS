"use client";
import { useEffect, useRef, useState } from "react";
import { read, RequestError } from "@/lib/client/api";
import { formatLocation } from "@/lib/client/library";
import type { CitationDetail } from "@/lib/client/retrieval-types";
import styles from "./teaching.module.css";

type State = { phase: "loading" } | { phase: "ready"; detail: CitationDetail } | { phase: "replaced" } | { phase: "error"; message: string };
/** Side drawer (native modal dialog: focus trap, Esc) that shows the verified source of a citation. */
export function CitationDrawer({ base, chunkId, title, onClose, onError }: { base: string; chunkId: string; title: string; onClose: () => void; onError: (e: unknown) => string }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [state, setState] = useState<State>({ phase: "loading" });
  useEffect(() => {
    const node = ref.current;
    const previous = document.activeElement as HTMLElement | null;
    node?.showModal();
    return () => { node?.close(); previous?.focus(); };
  }, []);
  useEffect(() => {
    let live = true;
    read(`${base}/citations/${encodeURIComponent(chunkId)}`).then(
      (detail: CitationDetail) => { if (live) setState({ phase: "ready", detail }); },
      (e: unknown) => { if (live) setState(e instanceof RequestError && e.status === 404 ? { phase: "replaced" } : { phase: "error", message: onError(e) }); },
    );
    return () => { live = false; };
  }, [base, chunkId, onError]);
  return <dialog ref={ref} className={styles.drawer} aria-labelledby="drawer-title" onCancel={event => { event.preventDefault(); onClose(); }}>
    <div className={styles.head}><h2 id="drawer-title">Nguồn trích dẫn</h2><button className="button button-secondary" onClick={onClose} aria-label="Đóng nguồn trích dẫn">Đóng</button></div>
    <div aria-live="polite">
      {state.phase === "loading" && <p role="status">Đang tải nguồn…</p>}
      {state.phase === "replaced" && <p role="alert" className={styles.abstain}>Nguồn này thuộc phiên bản đã thay thế</p>}
      {state.phase === "error" && <p role="alert" className={styles.error}>{state.message}</p>}
      {state.phase === "ready" && <>
        <p className={styles.cite}>{state.detail.fileName}</p>
        <p className={styles.muted}>{title}{formatLocation(state.detail) ? " · " + formatLocation(state.detail) : ""}</p>
        <pre className={styles.mono}>{state.detail.snippet}</pre>
      </>}
    </div>
  </dialog>;
}
