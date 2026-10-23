"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { components } from "@/lib/api/generated";
import { jsonInit, read } from "@/lib/client/api";
import {
  blueprintTotals, buildBlueprintBody, COGNITIVE_LABEL, COGNITIVE_LEVELS, deriveMatrix, normalizeBlueprintBody, removeAt, renumberSlots, replaceAt,
  type BlueprintBody, type Cognitive, type Part, type Slot,
} from "@/lib/client/authoring";
import { Chip, dateTime, useSubjects, useUnits } from "./authoring-shared";
import { BP_STATUS } from "./blueprints-screen";
import { ExamFromBlueprint } from "./exam-from-blueprint";
import { TeachingNav } from "./teaching-nav";
import { useTeaching } from "./use-teaching";
import styles from "./teaching.module.css";

type Detail = components["schemas"]["BlueprintDetailDTO"];
type Version = components["schemas"]["BlueprintVersionDTO"];
type Report = components["schemas"]["ValidationReportDTO"];

export function BlueprintDetailScreen({ blueprintId }: { blueprintId: string }) {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const base = workspace ? `/api/backend/workspaces/${workspace.id}/blueprints/${blueprintId}` : "";
  const [detail, setDetail] = useState<Detail | null>(null);
  const [version, setVersion] = useState<Version | null>(null);
  const [body, setBody] = useState<BlueprintBody | null>(null);
  const [dirty, setDirty] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loadingDetail, setLoadingDetail] = useState(true);

  const load = useCallback(async () => {
    if (!base) return;
    try {
      const d: Detail = await read(base);
      setDetail(d); setVersion(d.latestVersion);
      setBody(normalizeBlueprintBody(d.latestVersion?.body));
      setReport(d.latestVersion?.validationReport || null);
      setDirty(false); setError("");
    } catch (e) { setError(handle(e)); }
    finally { setLoadingDetail(false); }
  }, [base, handle]);
  // Network synchronisation on workspace change.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, [load]);

  const { subjects } = useSubjects(handle);
  const subjectCode = detail ? subjects.find(s => s.id === detail.subjectId)?.code || "" : "";
  const units = useUnits(subjectCode, detail ? String(detail.grade) : "", handle);
  const unitTitle = useMemo(() => Object.fromEntries(units.map(u => [u.id, `${u.unitCode} · ${u.titleVi}`])), [units]);

  const edit = (next: BlueprintBody) => { setBody(next); setDirty(true); setNotice(""); };
  const totals = useMemo(() => body ? blueprintTotals(body) : null, [body]);
  const locked = detail?.status === "published" && !dirty;

  async function saveVersion(): Promise<Version | null> {
    if (!body) return null;
    setBusy("save"); setError(""); setNotice("");
    try {
      const saved: Version = await read(`${base}/versions`, jsonInit(csrf, { body: buildBlueprintBody(body), expectedVersionNo: detail?.latestVersionNo ?? null }));
      setVersion(saved); setReport(saved.validationReport); setDirty(false);
      setNotice(`Đã lưu phiên bản ${saved.versionNo}.`);
      const d: Detail = await read(base); setDetail(d);
      return saved;
    } catch (e) { setError(handle(e)); return null; }
    finally { setBusy(""); }
  }
  async function validate() {
    if (!version) return;
    setBusy("validate"); setError(""); setNotice("");
    try {
      const checked: Version = await read(`${base}/versions/${version.versionNo}/validate`, jsonInit(csrf));
      setVersion(checked); setReport(checked.validationReport);
      setDetail(await read(base));
    } catch (e) { setError(handle(e)); }
    finally { setBusy(""); }
  }
  async function publish() {
    if (!version) return;
    setBusy("publish"); setError(""); setNotice("");
    try {
      await read(`${base}/versions/${version.versionNo}/publish`, jsonInit(csrf));
      setNotice("Đã xuất bản ma trận đề."); await load();
    } catch (e) { setError(handle(e)); }
    finally { setBusy(""); }
  }

  const setPart = (pi: number, part: Part) => body && edit(renumberSlots({ ...body, parts: replaceAt(body.parts, pi, part) }));
  const setSlot = (pi: number, si: number, patch: Partial<Slot>) => body && setPart(pi, { ...body.parts[pi], slots: replaceAt(body.parts[pi].slots, si, { ...body.parts[pi].slots[si], ...patch }) });
  const setDifficulty = (pi: number, si: number, value: string) => {
    if (!body) return;
    const { difficulty, ...rest } = body.parts[pi].slots[si];
    void difficulty;
    setPart(pi, { ...body.parts[pi], slots: replaceAt(body.parts[pi].slots, si, value ? { ...rest, difficulty: Number(value) } : rest) });
  };
  const canPublish = !dirty && !!version && report?.ok === true && version.status !== "published" && busy === "";
  const unitOptions = (current: string) => <>
    <option value="">Chọn đơn vị</option>
    {current && !unitTitle[current] && <option value={current}>{current.slice(0, 8)}</option>}
    {units.map(u => <option key={u.id} value={u.id}>{u.unitCode} · {u.titleVi}</option>)}
  </>;

  return <div className={styles.page}><div className={styles.wrap}>
    <TeachingNav current="blueprints" />
    <Link className={styles.back} href="/dashboard/blueprints">← Quay lại Ma trận đề</Link>
    <section className={styles.card} aria-busy={phase === "loading" || loadingDetail}>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {phase === "ready" && loadingDetail && <p role="status">Đang tải ma trận…</p>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
      {notice && <p role="status" className={styles.notice}>{notice}</p>}
      {detail && body && totals && <>
        <div className={styles.head}><h1>{detail.title}</h1><Chip label={BP_STATUS[detail.status][0]} tone={BP_STATUS[detail.status][1]} /></div>
        <p className={styles.muted}>Lớp {detail.grade} · {detail.durationMinutes} phút · {detail.totalPoints} điểm · cập nhật {dateTime(detail.updatedAt)} · phiên bản mới nhất: {detail.latestVersionNo}</p>
        <div className={styles.counts} aria-label="Tổng hợp">
          <div><strong>{totals.slots}</strong>câu</div><div><strong>{totals.points}</strong>điểm (khai báo {detail.totalPoints})</div>
          {COGNITIVE_LEVELS.map(c => <div key={c}><strong>{totals.byLevel[c]}</strong>{COGNITIVE_LABEL[c]}</div>)}
        </div>
        {detail.status === "published" && <div className={styles.actions}><ExamFromBlueprint wsBase={`/api/backend/workspaces/${workspace?.id}`} csrf={csrf} versionId={dirty ? null : detail.currentVersionId} grade={detail.grade} subject={subjectCode} onError={handle} /></div>}
        {locked && <p className={styles.notice} role="note">Phiên bản này đã xuất bản. Chỉnh sửa và lưu sẽ tạo phiên bản mới.</p>}

        <h2>Cấu trúc đề</h2>
        {body.parts.map((part, pi) => <fieldset key={pi} className={styles.section}>
          <legend>Phần {part.code || pi + 1}</legend>
          <div className={styles.tagGrid}>
            <label className={styles.field}><span>Mã phần {pi + 1}</span><input value={part.code} maxLength={20} onChange={e => setPart(pi, { ...part, code: e.target.value })} /></label>
            <label className={styles.field}><span>Tên phần {pi + 1}</span><input value={part.title} maxLength={200} onChange={e => setPart(pi, { ...part, title: e.target.value })} /></label>
          </div>
          {part.slots.length > 0 && <div className={styles.tableWrap}><table className={styles.table}>
            <caption className="sr-only">Các câu của phần {part.code || pi + 1}</caption>
            <thead><tr><th scope="col">Câu</th><th scope="col">Điểm</th><th scope="col">Đơn vị kiến thức</th><th scope="col">Mức nhận thức</th><th scope="col">Độ khó</th><th scope="col"><span className="sr-only">Xóa</span></th></tr></thead>
            <tbody>{part.slots.map((slot, si) => <tr key={si}>
              <td>{slot.index}</td>
              <td><input className={styles.cell} inputMode="decimal" aria-label={`Điểm câu ${slot.index}`} value={String(slot.points)} onChange={e => { const v = Number(e.target.value); if (Number.isFinite(v) && v >= 0) setSlot(pi, si, { points: v }); }} /></td>
              <td><select className={styles.cell} aria-label={`Đơn vị kiến thức câu ${slot.index}`} value={slot.curriculumUnitId} onChange={e => setSlot(pi, si, { curriculumUnitId: e.target.value })}>{unitOptions(slot.curriculumUnitId)}</select></td>
              <td><select className={styles.cell} aria-label={`Mức nhận thức câu ${slot.index}`} value={slot.cognitiveLevel} onChange={e => setSlot(pi, si, { cognitiveLevel: e.target.value as Cognitive })}>{COGNITIVE_LEVELS.map(c => <option key={c} value={c}>{COGNITIVE_LABEL[c]}</option>)}</select></td>
              <td><select className={styles.cell} aria-label={`Độ khó câu ${slot.index}`} value={slot.difficulty ?? ""} onChange={e => setDifficulty(pi, si, e.target.value)}><option value="">—</option>{[1, 2, 3, 4, 5].map(d => <option key={d} value={d}>{d}</option>)}</select></td>
              <td><button className="button button-secondary" aria-label={`Xóa câu ${slot.index}`} onClick={() => setPart(pi, { ...part, slots: removeAt(part.slots, si) })}>Xóa</button></td>
            </tr>)}</tbody>
          </table></div>}
          <div className={styles.actions}>
            <button className="button button-secondary" disabled={units.length === 0} onClick={() => setPart(pi, { ...part, slots: [...part.slots, { index: 0, itemType: "single_choice", points: 0.25, curriculumUnitId: units[0]?.id || "", cognitiveLevel: "remember" }] })}>Thêm câu</button>
            <button className="button button-secondary" aria-label={`Xóa phần ${part.code || pi + 1}`} disabled={body.parts.length <= 1} onClick={() => edit(renumberSlots({ ...body, parts: removeAt(body.parts, pi) }))}>Xóa phần</button>
          </div>
        </fieldset>)}
        <div><button className="button button-secondary" onClick={() => edit({ ...body, parts: [...body.parts, { code: String(body.parts.length + 1), title: "", slots: [] }] })}>Thêm phần</button></div>

        <h2>Ma trận (đơn vị × mức nhận thức)</h2>
        <div className={styles.actions}><button className="button button-secondary" onClick={() => edit({ ...body, matrix: deriveMatrix(body) })}>Tạo ma trận từ các câu</button>
          <button className="button button-secondary" disabled={units.length === 0} onClick={() => edit({ ...body, matrix: [...body.matrix, { curriculumUnitId: units[0]?.id || "", cognitiveLevel: "remember", count: 1 }] })}>Thêm dòng</button></div>
        {body.matrix.length > 0 && <div className={styles.tableWrap}><table className={styles.table}>
          <caption className="sr-only">Ma trận đề</caption>
          <thead><tr><th scope="col">Đơn vị kiến thức</th><th scope="col">Mức nhận thức</th><th scope="col">Số câu</th><th scope="col"><span className="sr-only">Xóa</span></th></tr></thead>
          <tbody>{body.matrix.map((row, mi) => <tr key={mi}>
            <td><select className={styles.cell} aria-label={`Đơn vị dòng ${mi + 1}`} value={row.curriculumUnitId} onChange={e => edit({ ...body, matrix: replaceAt(body.matrix, mi, { ...row, curriculumUnitId: e.target.value }) })}>{unitOptions(row.curriculumUnitId)}</select></td>
            <td><select className={styles.cell} aria-label={`Mức nhận thức dòng ${mi + 1}`} value={row.cognitiveLevel} onChange={e => edit({ ...body, matrix: replaceAt(body.matrix, mi, { ...row, cognitiveLevel: e.target.value as Cognitive }) })}>{COGNITIVE_LEVELS.map(c => <option key={c} value={c}>{COGNITIVE_LABEL[c]}</option>)}</select></td>
            <td><input className={styles.cell} inputMode="numeric" aria-label={`Số câu dòng ${mi + 1}`} value={String(row.count)} onChange={e => { const v = Math.trunc(Number(e.target.value)); if (Number.isFinite(v) && v >= 0 && v <= 500) edit({ ...body, matrix: replaceAt(body.matrix, mi, { ...row, count: v }) }); }} /></td>
            <td><button className="button button-secondary" aria-label={`Xóa dòng ${mi + 1}`} onClick={() => edit({ ...body, matrix: removeAt(body.matrix, mi) })}>Xóa</button></td>
          </tr>)}</tbody>
        </table></div>}
        <p className={totals.mismatches.length ? styles.error : styles.muted} role="status">
          {totals.matrixCount} câu trong ma trận, {totals.slots} câu trong cấu trúc đề.{totals.mismatches.length ? ` ${totals.mismatches.length} ô chưa khớp: ${totals.mismatches.slice(0, 4).map(m => `${unitTitle[m.curriculumUnitId] || m.curriculumUnitId.slice(0, 8)} / ${COGNITIVE_LABEL[m.cognitiveLevel]} (ma trận ${m.matrix}, đề ${m.slots})`).join("; ")}${totals.mismatches.length > 4 ? "…" : ""}.` : ""}
        </p>

        <div className={styles.toolbar}>
          <div className={styles.actions}>
            <button className="button button-primary" disabled={!dirty || busy !== ""} onClick={() => void saveVersion()}>{busy === "save" ? "Đang lưu…" : "Lưu phiên bản"}</button>
            <button className="button button-secondary" disabled={dirty || !version || busy !== ""} onClick={() => void validate()}>{busy === "validate" ? "Đang kiểm tra…" : "Kiểm tra"}</button>
            <button className="button button-primary" disabled={!canPublish} onClick={() => void publish()}>{busy === "publish" ? "Đang xuất bản…" : "Xuất bản"}</button>
          </div>
          {dirty && <span className={styles.muted} role="status">Có thay đổi chưa lưu. Hãy lưu phiên bản trước khi kiểm tra.</span>}
        </div>
        {report && !dirty && <div aria-live="polite" className={styles.report}>
          <p><Chip label={report.ok ? "Hợp lệ" : "Chưa hợp lệ"} tone={report.ok ? undefined : "error"} /> {version ? `Phiên bản ${version.versionNo}` : ""}</p>
          {report.errors.length > 0 && <><h3>Lỗi</h3><ul className={styles.list}>{report.errors.map((x, i) => <li key={i} className={styles.error}>{x.message} <small>({x.code}{x.path ? ` · ${x.path}` : ""})</small></li>)}</ul></>}
          {report.warnings.length > 0 && <><h3>Cảnh báo</h3><ul className={styles.list}>{report.warnings.map((x, i) => <li key={i}>{x.message} <small>({x.code}{x.path ? ` · ${x.path}` : ""})</small></li>)}</ul></>}
        </div>}

        <h2>Các phiên bản</h2>
        <div className={styles.tableWrap}><table className={styles.table}>
          <caption className="sr-only">Lịch sử phiên bản</caption>
          <thead><tr><th scope="col">Bản</th><th scope="col">Trạng thái</th><th scope="col">Kiểm tra</th><th scope="col">Tạo lúc</th></tr></thead>
          <tbody>{detail.versions.slice().sort((a, b) => b.versionNo - a.versionNo).map(v => <tr key={v.id}>
            <td>{v.versionNo}</td><td><Chip label={BP_STATUS[v.status][0]} tone={BP_STATUS[v.status][1]} /></td><td>{v.validationReport.ok ? "Hợp lệ" : `${v.validationReport.errors.length} lỗi`}</td><td>{dateTime(v.createdAt)}</td>
          </tr>)}</tbody>
        </table></div>
      </>}
    </section>
  </div></div>;
}
