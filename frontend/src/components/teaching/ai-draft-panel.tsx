"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import type { components } from "@/lib/api/generated";
import { jsonInit, read, RequestError } from "@/lib/client/api";
import { isTerminal, nextDelay } from "@/lib/client/jobs";
import { AI_UNAVAILABLE_MESSAGE, buildDraftRequest, generationOutcome, isAiUnavailableCode, type DraftRequest, type Outcome } from "@/lib/client/generation";
import { UnitPicker, type Subject } from "./authoring-shared";
import styles from "./teaching.module.css";

type Accepted = components["schemas"]["GenerationAcceptedDTO"];
type GenerationJob = components["schemas"]["GenerationJobDTO"];
type Job = components["schemas"]["JobDTO"];
type Doc = components["schemas"]["DocumentDTO"];
const MAX_POLLS = 90;
const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

export type DraftResult = { contentItemId: string | null; revisionNo: number | null };

/** Submits a draft generation and polls the background job, then the generation job. Prompts and bodies are never logged. */
export async function runDraftGeneration(wsBase: string, csrf: string, request: DraftRequest, isAlive: () => boolean, onStatus: (text: string) => void): Promise<Outcome | null> {
  let accepted: Accepted;
  try { accepted = await read(`${wsBase}/generation/drafts`, jsonInit(csrf, request), 30000); }
  catch (e) {
    if (e instanceof RequestError && (e.status === 503 || isAiUnavailableCode(e.code))) return { kind: "unavailable", message: AI_UNAVAILABLE_MESSAGE };
    throw e;
  }
  onStatus("Đã gửi yêu cầu, đang tạo bản nháp…");
  let errors = 0;
  let status: Job["status"] = accepted.job.status;
  for (let i = 0; i < MAX_POLLS && !isTerminal(status); i++) {
    await sleep(nextDelay(errors));
    if (!isAlive()) return null;
    try { status = (await read(`${wsBase}/jobs/${accepted.job.id}`) as Job).status; errors = 0; }
    catch (e) { if (e instanceof RequestError && e.status === 401) throw e; if (++errors >= 5) throw e; }
  }
  onStatus("Đang kiểm tra bản nháp…");
  let generation: GenerationJob = accepted.generationJob;
  for (let i = 0; i < 20; i++) {
    try { generation = await read(`${wsBase}/generation/jobs/${accepted.generationJob.id}`); }
    catch (e) { if (e instanceof RequestError && e.status === 401) throw e; if (++errors >= 5) throw e; }
    const outcome = generationOutcome(generation);
    if (outcome.kind !== "pending") return outcome;
    if (status === "failed" || status === "cancelled") return { kind: "failed", message: "Không tạo được bản nháp AI. Bạn vẫn soạn tay được.", code: "job_" + status };
    await sleep(nextDelay(errors));
    if (!isAlive()) return null;
  }
  return { kind: "failed", message: "Bản nháp AI chưa hoàn tất sau thời gian chờ. Bạn vẫn soạn tay được.", code: "generation_timeout" };
}

export function AiDraftPanel({ wsBase, csrf, itemId, kind, unitId, beforeStart, onDone, onError }: {
  wsBase: string; csrf: string; itemId: string; kind: "lesson_plan" | "study_guide"; unitId: string | null;
  beforeStart: () => Promise<boolean>; onDone: (result: DraftResult) => Promise<void>; onError: (e: unknown) => string;
}) {
  const [objectives, setObjectives] = useState("");
  const [duration, setDuration] = useState("45");
  const [unit, setUnit] = useState(unitId || "");
  const [subject, setSubject] = useState<{ subject: Subject | null; grade: number | null }>({ subject: null, grade: null });
  const [docs, setDocs] = useState<Doc[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [problem, setProblem] = useState<Outcome | null>(null);
  const [formError, setFormError] = useState("");
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    let live = true;
    read(`${wsBase}/documents?limit=50`).then((res: { items: Doc[] }) => { if (live) setDocs(res.items.filter(d => d.status === "uploaded")); }, () => { /* optional list; manual flow unaffected */ });
    return () => { live = false; };
  }, [wsBase]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setProblem(null); setFormError("");
    const built = buildDraftRequest({ purpose: kind, curriculumUnitId: unit, grade: subject.grade, subject: subject.subject?.code || "", objectivesText: objectives, duration, documentIds: picked, contentItemId: itemId });
    if (!built.ok) { setFormError(built.message); return; }
    setBusy(true); setStatus("Đang lưu bản nháp hiện tại…");
    try {
      if (!(await beforeStart())) { setFormError("Hãy xử lý lỗi lưu bản nháp trước khi nhờ AI soạn."); return; }
      setStatus("Đang gửi yêu cầu…");
      const outcome = await runDraftGeneration(wsBase, csrf, built.value, () => alive.current, text => { if (alive.current) setStatus(text); });
      if (!alive.current || !outcome) return;
      if (outcome.kind === "success") { setStatus("Đã tạo bản nháp. Đang mở…"); await onDone({ contentItemId: outcome.contentItemId, revisionNo: outcome.revisionNo }); setStatus(""); }
      else { setProblem(outcome); setStatus(""); }
    } catch (e) { if (alive.current) { setFormError(onError(e)); setStatus(""); } }
    finally { if (alive.current) setBusy(false); }
  }
  return <aside className={styles.aiPanel} aria-label="Soạn cùng AI">
    <h2>Soạn cùng AI</h2>
    <p className={styles.muted}>AI tạo bản nháp mới dựa trên tài liệu bạn chọn. Bản nháp luôn cần bạn kiểm tra nguồn và duyệt.</p>
    <form className={styles.dialogBody} onSubmit={event => void submit(event)}>
      <UnitPicker unitId={unit} onUnit={setUnit} onSubject={(s, g) => setSubject({ subject: s, grade: g })} onError={onError} required />
      <label className={styles.field}><span>Mục tiêu bài học (mỗi dòng một mục tiêu) *</span>
        <textarea rows={4} value={objectives} maxLength={3000} onChange={e => setObjectives(e.target.value)} disabled={busy} /></label>
      <label className={styles.field}><span>Thời lượng (phút)</span><input inputMode="numeric" value={duration} onChange={e => setDuration(e.target.value)} disabled={busy} /></label>
      <fieldset className={styles.docPick} disabled={busy}>
        <legend>Tài liệu nguồn (tùy chọn)</legend>
        {docs.length === 0 && <span className={styles.muted}>Chưa có tài liệu sẵn sàng.</span>}
        {docs.map(doc => <label key={doc.id} className={styles.check}><input type="checkbox" checked={picked.includes(doc.id)} onChange={e => setPicked(current => e.target.checked ? [...current, doc.id] : current.filter(id => id !== doc.id))} /><span>{doc.fileName}</span></label>)}
      </fieldset>
      {formError && <p role="alert" className={styles.error}>{formError}</p>}
      {problem && problem.kind === "unavailable" && <p role="alert" className={styles.notice}>{problem.message}</p>}
      {problem && problem.kind === "invalid" && <div role="alert" className={styles.banner}>
        <div><strong>{problem.message}</strong>{problem.reasons.length > 0 && <ul>{problem.reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul>}</div></div>}
      {problem && problem.kind === "failed" && <p role="alert" className={styles.error}>{problem.message} <small>({problem.code})</small></p>}
      <p role="status" aria-live="polite" className={styles.muted}>{status}</p>
      <button className="button button-primary" type="submit" disabled={busy}>{busy ? "Đang tạo…" : "Tạo bản nháp AI"}</button>
    </form>
  </aside>;
}
