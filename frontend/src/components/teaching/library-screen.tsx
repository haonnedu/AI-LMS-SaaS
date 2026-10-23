"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { components } from "@/lib/api/generated";
import { read } from "@/lib/client/api";
import { buildQueryBody, citationLabel, formatLocation, groupByDocument, QUERY_MAX, titleMap, toggleId, validateQuery } from "@/lib/client/library";
import type { RetrievalResponse } from "@/lib/client/retrieval-types";
import { CitationDrawer } from "./citation-drawer";
import { TeachingNav } from "./teaching-nav";
import { useTeaching } from "./use-teaching";
import styles from "./teaching.module.css";

type Doc = components["schemas"]["DocumentDTO"];
const MAX_DOC_PAGES = 5;

export function LibraryScreen() {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [fieldError, setFieldError] = useState("");
  const [error, setError] = useState("");
  const [searching, setSearching] = useState(false);
  const [result, setResult] = useState<RetrievalResponse | null>(null);
  const [open, setOpen] = useState<{ chunkId: string; title: string } | null>(null);
  const searchEpoch = useRef(0);
  const base = workspace ? `/api/backend/workspaces/${workspace.id}` : "";

  useEffect(() => {
    if (!base) return;
    let live = true;
    (async () => {
      try {
        let all: Doc[] = [];
        let cursor: string | null = null;
        for (let page = 0; page < MAX_DOC_PAGES; page++) {
          const res: { items: Doc[]; nextCursor: string | null } = await read(`${base}/documents?limit=50${cursor ? "&cursor=" + encodeURIComponent(cursor) : ""}`);
          all = all.concat(res.items);
          cursor = res.nextCursor;
          if (!cursor) break;
        }
        if (live) setDocs(all.filter(d => d.status === "uploaded"));
      } catch (e) { if (live) setError(handle(e)); }
    })();
    return () => { live = false; };
  }, [base, handle]);

  async function search(event: FormEvent) {
    event.preventDefault();
    const checked = validateQuery(text);
    if (!checked.ok) { setFieldError(checked.error); return; }
    const body = buildQueryBody(text, selected);
    if (!body || !base) return;
    const version = ++searchEpoch.current;
    setFieldError(""); setError(""); setSearching(true);
    try {
      const response: RetrievalResponse = await read(`${base}/retrieval/query`, { method: "POST", headers: { "X-CSRF-Token": csrf, "Content-Type": "application/json" }, body: JSON.stringify(body) }, 30000);
      if (version === searchEpoch.current) setResult(response);
    } catch (e) { if (version === searchEpoch.current) { setResult(null); setError(handle(e)); } }
    finally { if (version === searchEpoch.current) setSearching(false); }
  }
  const titles = titleMap(docs);
  const closeDrawer = useCallback(() => setOpen(null), []);
  const groups = result ? groupByDocument(result.items) : [];
  const abstain = result !== null && (result.abstained || result.items.length === 0);

  return <div className={styles.page}><div className={styles.wrap}>
    <TeachingNav current="library" />
    <section className={styles.card} aria-busy={searching || phase === "loading"}>
      <div className={styles.head}><h1>Thư viện học liệu</h1>{workspace && <span className={styles.muted}>{workspace.name}</span>}</div>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {phase === "ready" && <form onSubmit={event => void search(event)} className={styles.form} style={{ gridTemplateColumns: "1fr" }} role="search" aria-label="Tìm trong tài liệu">
        <div className={styles.searchRow}>
          <label className={styles.field}><span>Tìm trong tài liệu của tôi</span>
            <input type="search" value={text} maxLength={QUERY_MAX} onChange={e => setText(e.target.value)} placeholder="Ví dụ: cách cộng hai phân số" aria-describedby={fieldError ? "query-error" : undefined} aria-invalid={fieldError ? true : undefined} /></label>
          <button className="button button-primary" type="submit" disabled={searching}>{searching ? "Đang tìm…" : "Tìm kiếm"}</button>
        </div>
        {fieldError && <p id="query-error" role="alert" className={styles.error}>{fieldError}</p>}
        {docs.length > 0 && <fieldset className={styles.docFilter}><legend>Lọc theo tài liệu (để trống: tìm tất cả)</legend>
          {docs.map(doc => <label key={doc.id} className={styles.check}><input type="checkbox" checked={selected.includes(doc.id)} onChange={() => setSelected(current => toggleId(current, doc.id))} /><span>{doc.fileName}</span></label>)}
        </fieldset>}
      </form>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
    </section>
    {phase === "ready" && result && <section className={styles.card} aria-label="Kết quả tìm kiếm" aria-live="polite">
      {abstain ? <p role="status" className={styles.abstain}>Không tìm thấy đoạn phù hợp trong tài liệu được phép</p> : groups.map(group => <div key={group.documentId} className={styles.list}>
        <h2>{titles[group.documentId] || "Tài liệu"}</h2>
        {group.items.map(item => {
          const title = titles[item.documentId] || "Tài liệu";
          const location = formatLocation(item);
          return <article key={item.chunkId} className={styles.resultCard}>
            <p className={styles.cite}>{citationLabel(item, title)}</p>
            <p>{item.snippet}</p>
            <small className={styles.muted}>{title}{location ? " · " + location : ""}</small>
            <div className={styles.actions}>
              <button className="button button-secondary" onClick={() => setOpen({ chunkId: item.chunkId, title })} aria-label={`Xem nguồn: ${citationLabel(item, title) || title}`}>Xem nguồn</button>
              <Link className="button button-secondary" href={`/dashboard/library/${item.documentId}`}>Mở tài liệu</Link>
            </div>
          </article>;
        })}
      </div>)}
    </section>}
    {open && base && <CitationDrawer key={open.chunkId} base={base} chunkId={open.chunkId} title={open.title} onClose={closeDrawer} onError={handle} />}
  </div></div>;
}
