"use client";
import { useEffect, useState } from "react";
import type { components } from "@/lib/api/generated";
import { read } from "@/lib/client/api";
import { canViewSource, provenanceStatus, sourceLocation, sourceSnippet } from "@/lib/client/generation";
import { Chip } from "./authoring-shared";
import styles from "./teaching.module.css";

export type Provenance = components["schemas"]["ProvenanceDTO"];
type Source = components["schemas"]["ProvenanceSourceDTO"];
const VALIDATION: Record<string, string> = { pending: "Đang chờ kiểm tra", valid: "Đạt kiểm tra", invalid: "Không đạt kiểm tra", failed: "Kiểm tra lỗi" };

/** Loads provenance for one revision. `reloadKey` re-fetches after approvals. Errors leave data null (manual content has none). */
export function useProvenance(base: string, revisionNo: number | null, reloadKey: string) {
  const [state, setState] = useState<{ key: string; data: Provenance | null; error: string }>({ key: "", data: null, error: "" });
  const key = base && revisionNo ? `${base}|${revisionNo}|${reloadKey}` : "";
  useEffect(() => {
    if (!key) return;
    let live = true;
    read(`${base}/revisions/${revisionNo}/provenance`).then(
      (data: Provenance) => { if (live) setState({ key, data, error: "" }); },
      () => { if (live) setState({ key, data: null, error: "Chưa tải được nguồn của bản này." }); },
    );
    return () => { live = false; };
  }, [key, base, revisionNo]);
  const current = state.key === key;
  return { data: current ? state.data : null, error: current ? state.error : "", loading: !!key && !current };
}

export function ProvenancePanel({ data, loading, error, onView }: { data: Provenance | null; loading: boolean; error: string; onView: (source: Source) => void }) {
  if (loading) return <p role="status">Đang tải nguồn…</p>;
  if (error) return <p role="alert" className={styles.error}>{error}</p>;
  if (!data) return <p className={styles.muted}>Chưa có thông tin nguồn.</p>;
  return <div className={styles.dialogBody}>
    {data.generationJobId
      ? <p className={styles.muted}>Bản này do AI tạo{data.provider ? ` (${data.provider}${data.model ? " / " + data.model : ""})` : ""}{data.promptVersion ? ` · prompt ${data.promptVersion}` : ""}{data.validationStatus ? ` · ${VALIDATION[data.validationStatus] || data.validationStatus}` : ""}.</p>
      : <p className={styles.muted}>Bản này do giáo viên soạn tay.</p>}
    {data.sources.length === 0 && <p className={styles.muted}>Bản này chưa có nguồn trích dẫn.</p>}
    <ul className={styles.srcList} aria-label="Danh sách nguồn">{data.sources.map((source, i) => {
      const status = provenanceStatus(source.status);
      const snippet = sourceSnippet(source);
      const where = sourceLocation(source);
      return <li key={source.chunkId || i} className={styles.srcItem} data-status={source.status}>
        <div className={styles.actions}><strong>{source.label || "Nguồn"}</strong><Chip label={status.label} tone={status.tone} />{!source.cited && <Chip label="Chưa được trích" tone="warn" />}</div>
        {where && <small className={styles.muted}>{where}</small>}
        {source.status === "withdrawn" ? <p className={styles.error}>Nguồn không còn tồn tại</p> : snippet && <pre className={styles.mono}>{snippet}</pre>}
        {source.status === "superseded" && <small className={styles.muted}>Tài liệu đã có phiên bản mới hơn. Hãy kiểm tra lại nội dung trích dẫn.</small>}
        {canViewSource(source) && <div><button type="button" className="button button-secondary" onClick={() => onView(source)} aria-label={`Xem nguồn ${source.label || i + 1}`}>Xem nguồn</button></div>}
      </li>;
    })}</ul>
  </div>;
}
