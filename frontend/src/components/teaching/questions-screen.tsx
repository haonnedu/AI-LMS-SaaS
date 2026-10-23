"use client";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { components } from "@/lib/api/generated";
import { jsonInit, read, RequestError } from "@/lib/client/api";
import {
  buildQuestionBody, CHOICE_KEYS, COGNITIVE_LABEL, COGNITIVE_LEVELS, CSV_MAX_BYTES, emptyQuestionForm, previewCsv, questionFormFrom, questionQuery, validateQuestionForm,
  type CsvPreview, type QuestionForm,
} from "@/lib/client/authoring";
import { mergeById } from "@/lib/client/library";
import { Chip, UnitPicker, unitLabel, type Tone } from "./authoring-shared";
import { Modal } from "./modal";
import { TeachingNav } from "./teaching-nav";
import { useTeaching } from "./use-teaching";
import styles from "./teaching.module.css";

type Summary = components["schemas"]["QuestionSummaryDTO"];
type Detail = components["schemas"]["TeacherQuestionDTO"];
type ImportResult = components["schemas"]["ImportResultDTO"];
const STATUS: Record<Summary["status"], [string, Tone]> = { draft: ["Nháp", "warn"], active: ["Đang dùng", undefined], retired: ["Đã gỡ", "error"] };

export function QuestionsScreen({ initialStatus = "" }: { initialStatus?: string } = {}) {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const base = workspace ? `/api/backend/workspaces/${workspace.id}/questions` : "";
  const [items, setItems] = useState<Summary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [filters, setFilters] = useState({ status: initialStatus, difficulty: "", cognitiveLevel: "", unitId: "", q: "" });
  const [applied, setApplied] = useState(filters);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editor, setEditor] = useState<{ id: string | null } | null>(null);
  const [retire, setRetire] = useState<Summary | null>(null);
  const [importing, setImporting] = useState(false);
  const epoch = useRef(0);

  const load = useCallback(async (after: string | null) => {
    if (!base) return;
    const mine = ++epoch.current;
    setLoading(true); setError("");
    try {
      const page: { items: Summary[]; nextCursor: string | null } = await read(base + questionQuery(applied, after));
      if (mine !== epoch.current) return;
      setItems(current => after ? mergeById(current, page.items) : page.items);
      setCursor(page.nextCursor);
    } catch (e) { if (mine === epoch.current) setError(handle(e)); }
    finally { if (mine === epoch.current) setLoading(false); }
  }, [base, applied, handle]);
  // Network synchronisation when applied filters or workspace change.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(null); }, [load]);

  async function doRetire(question: Summary) {
    setRetire(null); setError(""); setNotice("");
    try { await read(`${base}/${question.id}/retire`, jsonInit(csrf)); setNotice("Đã gỡ câu hỏi khỏi ngân hàng."); await load(null); }
    catch (e) { setError(handle(e)); }
  }
  async function download(audience: "teacher" | "student") {
    setError(""); setNotice("");
    try {
      const response = await fetch(`${base}/export?audience=${audience}`, { cache: "no-store", signal: AbortSignal.timeout(60000) });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new RequestError(response.status, payload?.error?.code || "request_failed", payload?.error?.message || "Chưa thể xuất tệp. Vui lòng thử lại.");
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = `questions-${audience}.csv`;
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice(audience === "student" ? "Đã xuất tệp cho học sinh (không có đáp án)." : "Đã xuất tệp cho giáo viên (có đáp án).");
    } catch (e) { setError(handle(e)); }
  }

  return <div className={styles.page}><div className={styles.wrap}>
    <TeachingNav current="questions" />
    <section className={styles.card} aria-busy={phase === "loading" || loading}>
      <div className={styles.head}><h1>Ngân hàng câu hỏi</h1>
        {phase === "ready" && <div className={styles.actions}>
          <button className="button button-primary" onClick={() => setEditor({ id: null })}>Thêm câu hỏi</button>
          <button className="button button-secondary" onClick={() => setImporting(true)}>Nhập CSV</button>
        </div>}
      </div>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {phase === "ready" && <>
        <form className={styles.form} role="search" aria-label="Lọc câu hỏi" onSubmit={event => { event.preventDefault(); setApplied(filters); }}>
          <label className={styles.field}><span>Tìm theo nội dung</span><input type="search" value={filters.q} maxLength={200} onChange={e => setFilters({ ...filters, q: e.target.value })} /></label>
          <label className={styles.field}><span>Trạng thái</span><select value={filters.status} onChange={e => setFilters({ ...filters, status: e.target.value })}><option value="">Tất cả</option>{Object.entries(STATUS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label className={styles.field}><span>Độ khó</span><select value={filters.difficulty} onChange={e => setFilters({ ...filters, difficulty: e.target.value })}><option value="">Tất cả</option>{[1, 2, 3, 4, 5].map(d => <option key={d} value={d}>{d}</option>)}</select></label>
          <label className={styles.field}><span>Mức nhận thức</span><select value={filters.cognitiveLevel} onChange={e => setFilters({ ...filters, cognitiveLevel: e.target.value })}><option value="">Tất cả</option>{COGNITIVE_LEVELS.map(c => <option key={c} value={c}>{COGNITIVE_LABEL[c]}</option>)}</select></label>
          <button className="button button-primary" type="submit">Lọc</button>
        </form>
        <details className={styles.docFilter}><summary>Lọc theo đơn vị kiến thức{filters.unitId ? ": " + unitLabel(filters.unitId) : ""}</summary>
          <UnitPicker unitId={filters.unitId} onUnit={unitId => setFilters(f => ({ ...f, unitId }))} onError={handle} />
          <p className={styles.muted}>Nhấn “Lọc” để áp dụng.</p>
        </details>
        <div className={styles.exportBox}>
          <div className={styles.actions}>
            <button className="button button-secondary" onClick={() => void download("teacher")}>Xuất CSV (giáo viên)</button>
            <button className="button button-secondary" onClick={() => void download("student")}>Xuất CSV (học sinh)</button>
          </div>
          <p className={styles.muted}>Tệp giáo viên có đáp án và giải thích, chỉ lưu nội bộ. Tệp học sinh không chứa đáp án hay giải thích và có thể chia sẻ.</p>
        </div>
        {error && <p role="alert" className={styles.error}>{error}</p>}
        {notice && <p role="status" className={styles.notice}>{notice}</p>}
        {!loading && !error && items.length === 0 && <p className={styles.muted}>Chưa có câu hỏi phù hợp.</p>}
        {items.length > 0 && <div className={styles.tableWrap}><table className={styles.table}>
          <caption className="sr-only">Danh sách câu hỏi</caption>
          <thead><tr><th scope="col">Câu hỏi</th><th scope="col">Mức</th><th scope="col">Độ khó</th><th scope="col">Đơn vị</th><th scope="col">Trạng thái</th><th scope="col"><span className="sr-only">Thao tác</span></th></tr></thead>
          <tbody>{items.map(q => <tr key={q.id}>
            <td>{q.stem.length > 140 ? q.stem.slice(0, 140) + "…" : q.stem}</td>
            <td>{COGNITIVE_LABEL[q.cognitiveLevel]}</td><td>{q.difficulty ?? "—"}</td><td>{unitLabel(q.curriculumUnitId)}</td>
            <td><Chip label={STATUS[q.status][0]} tone={STATUS[q.status][1]} /></td>
            <td><div className={styles.actions}>
              <button className="button button-secondary" disabled={q.status === "retired"} onClick={() => setEditor({ id: q.id })} aria-label={`Sửa câu hỏi: ${q.stem.slice(0, 40)}`}>Sửa</button>
              <button className="button button-secondary" disabled={q.status === "retired"} onClick={() => setRetire(q)} aria-label={`Gỡ câu hỏi: ${q.stem.slice(0, 40)}`}>Gỡ</button>
            </div></td>
          </tr>)}</tbody>
        </table></div>}
        {cursor && <button className="button button-secondary" disabled={loading} onClick={() => void load(cursor)}>Tải thêm</button>}
      </>}
    </section>
    {editor && base && <QuestionDialog key={editor.id || "new"} base={base} csrf={csrf} id={editor.id} onError={handle} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); setNotice("Đã lưu câu hỏi."); void load(null); }} />}
    {importing && base && <ImportDialog base={base} csrf={csrf} onError={handle} onClose={() => setImporting(false)} onDone={() => void load(null)} />}
    {retire && <Modal title="Gỡ câu hỏi?" onClose={() => setRetire(null)}>
      <p>Câu hỏi sẽ không còn được dùng cho đề mới. Nội dung vẫn được lưu để tra cứu.</p>
      <div className={styles.actions}><button className="button button-primary" onClick={() => void doRetire(retire)}>Gỡ câu hỏi</button><button className="button button-secondary" onClick={() => setRetire(null)}>Hủy</button></div>
    </Modal>}
  </div></div>;
}

function QuestionDialog({ base, csrf, id, onError, onClose, onSaved }: { base: string; csrf: string; id: string | null; onError: (e: unknown) => string; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState<QuestionForm>(emptyQuestionForm());
  const [revisionNo, setRevisionNo] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(id !== null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!id) return;
    let live = true;
    read(`${base}/${id}`).then((q: Detail) => { if (!live) return; setForm(questionFormFrom(q)); setRevisionNo(q.revisionNo); setLoading(false); }, (e: unknown) => { if (live) { setError(onError(e)); setLoading(false); } });
    return () => { live = false; };
  }, [base, id, onError]);
  const setChoice = (i: number, text: string) => setForm(f => ({ ...f, choices: f.choices.map((c, j) => j === i ? text : c) }));
  async function submit(event: FormEvent) {
    event.preventDefault();
    const checked = validateQuestionForm(form);
    if (!checked.ok) { setError(checked.error); return; }
    setSaving(true); setError("");
    try {
      if (id) {
        const saved: Detail = await read(`${base}/${id}`, { ...jsonInit(csrf, buildQuestionBody(form, revisionNo)), method: "PUT" });
        if (saved.correctKey !== form.correctKey) await read(`${base}/${id}/key`, { ...jsonInit(csrf, { correctKey: form.correctKey }), method: "PUT" });
      } else await read(base, jsonInit(csrf, buildQuestionBody(form)));
      onSaved();
    } catch (e) { setError(onError(e)); setSaving(false); }
  }
  return <Modal title={id ? "Sửa câu hỏi" : "Thêm câu hỏi"} onClose={() => !saving && onClose()}>
    {loading ? <p role="status">Đang tải…</p> : <form onSubmit={event => void submit(event)}>
      <label className={styles.field}><span>Nội dung câu hỏi *</span><textarea rows={3} value={form.stem} maxLength={5000} required onChange={e => setForm({ ...form, stem: e.target.value })} autoFocus /></label>
      <fieldset className={styles.docFilter}><legend>Các lựa chọn và đáp án đúng (chỉ giáo viên thấy)</legend>
        {form.choices.map((text, i) => <div key={i} className={styles.choiceRow}>
          <input type="radio" name="correct" aria-label={`Đáp án đúng là ${CHOICE_KEYS[i]}`} checked={form.correctKey === CHOICE_KEYS[i]} onChange={() => setForm({ ...form, correctKey: CHOICE_KEYS[i] })} />
          <label className={styles.field}><span>Lựa chọn {CHOICE_KEYS[i]}</span><input value={text} maxLength={1000} onChange={e => setChoice(i, e.target.value)} /></label>
          <button type="button" className="button button-secondary" aria-label={`Xóa lựa chọn ${CHOICE_KEYS[i]}`} disabled={form.choices.length <= 3} onClick={() => setForm(f => ({ ...f, choices: f.choices.filter((_, j) => j !== i), correctKey: f.correctKey === CHOICE_KEYS[i] ? "" : f.correctKey && CHOICE_KEYS.indexOf(f.correctKey) > i ? CHOICE_KEYS[CHOICE_KEYS.indexOf(f.correctKey) - 1] : f.correctKey }))}>Xóa</button>
        </div>)}
        <button type="button" className="button button-secondary" disabled={form.choices.length >= 5} onClick={() => setForm(f => ({ ...f, choices: [...f.choices, ""] }))}>Thêm lựa chọn</button>
      </fieldset>
      <div className={styles.tagGrid}>
        <label className={styles.field}><span>Độ khó</span><select value={form.difficulty} onChange={e => setForm({ ...form, difficulty: e.target.value })}><option value="">Chưa đặt</option>{[1, 2, 3, 4, 5].map(d => <option key={d} value={d}>{d}</option>)}</select></label>
        <label className={styles.field}><span>Mức nhận thức</span><select value={form.cognitiveLevel} onChange={e => setForm({ ...form, cognitiveLevel: e.target.value as QuestionForm["cognitiveLevel"] })}>{COGNITIVE_LEVELS.map(c => <option key={c} value={c}>{COGNITIVE_LABEL[c]}</option>)}</select></label>
      </div>
      <UnitPicker unitId={form.curriculumUnitId} onUnit={curriculumUnitId => setForm(f => ({ ...f, curriculumUnitId }))} onError={onError} />
      <label className={styles.field}><span>Giải thích (chỉ giáo viên thấy)</span><textarea rows={2} value={form.explanation} maxLength={10000} onChange={e => setForm({ ...form, explanation: e.target.value })} /></label>
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <div className={styles.actions}><button className="button button-primary" type="submit" disabled={saving}>{saving ? "Đang lưu…" : "Lưu câu hỏi"}</button><button className="button button-secondary" type="button" disabled={saving} onClick={onClose}>Hủy</button></div>
    </form>}
  </Modal>;
}

function ImportDialog({ base, csrf, onError, onClose, onDone }: { base: string; csrf: string; onError: (e: unknown) => string; onClose: () => void; onDone: () => void }) {
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState("");
  async function pick(file: File | undefined) {
    setResult(null); setError(""); setPreview(null); setText("");
    if (!file) return;
    if (file.size > CSV_MAX_BYTES) { setError("Tệp quá lớn (tối đa 2 MB)."); return; }
    const content = await file.text();
    setFileName(file.name); setText(content); setPreview(previewCsv(content));
  }
  async function send() {
    setSending(true); setError("");
    try {
      const res: ImportResult = await read(`${base}/import`, { method: "POST", headers: { "X-CSRF-Token": csrf, "Content-Type": "text/csv" }, body: text }, 60000);
      setResult(res);
      if (res.created > 0) onDone();
    } catch (e) { setError(onError(e)); }
    finally { setSending(false); }
  }
  return <Modal title="Nhập câu hỏi từ CSV" onClose={() => !sending && onClose()}>
    <div className={styles.dialogBody}>
      <p className={styles.muted}>Tệp UTF-8 có dòng tiêu đề: stem, choiceA…choiceE, correct, difficulty, cognitive, unitCode, explanation. Tối đa 2000 câu, 2 MB.</p>
      <label className={styles.field}><span>Chọn tệp CSV</span><input type="file" accept=".csv,text/csv" onChange={e => void pick(e.target.files?.[0])} /></label>
      {preview && <div>
        <p role="status">{fileName}: {preview.rowCount} dòng dữ liệu. {preview.ok ? "Định dạng hợp lệ ở bước kiểm tra sơ bộ." : "Có vấn đề cần sửa trước khi nhập."}</p>
        {preview.problems.length > 0 && <ul className={styles.list}>{preview.problems.slice(0, 10).map((p, i) => <li key={i} className={styles.error}>Dòng {p.row}: {p.message}</li>)}</ul>}
      </div>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
      {result && <div role="status">
        <p>Đã tạo {result.created} câu hỏi{result.duplicates.length ? `, bỏ qua ${result.duplicates.length} câu trùng` : ""}{result.errors.length ? `, ${result.errors.length} dòng lỗi` : ""}.</p>
        {result.errors.length > 0 && <div className={styles.tableWrap}><table className={styles.table}>
          <caption className="sr-only">Lỗi theo dòng</caption>
          <thead><tr><th scope="col">Dòng</th><th scope="col">Mã lỗi</th><th scope="col">Chi tiết</th></tr></thead>
          <tbody>{result.errors.map((er, i) => <tr key={i}><td>{er.row}</td><td>{er.code}</td><td>{er.message}</td></tr>)}</tbody>
        </table></div>}
        {result.duplicates.length > 0 && <p className={styles.muted}>Câu trùng ở dòng: {result.duplicates.map(d => d.row).join(", ")}.</p>}
      </div>}
      <div className={styles.actions}>
        <button className="button button-primary" disabled={!text || sending || !preview?.headerOk} onClick={() => void send()}>{sending ? "Đang nhập…" : "Nhập câu hỏi"}</button>
        <button className="button button-secondary" disabled={sending} onClick={onClose}>Đóng</button>
      </div>
    </div>
  </Modal>;
}
