"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { components } from "@/lib/api/generated";
import { jsonInit, read } from "@/lib/client/api";
import { EXAM_STATUS } from "@/lib/client/generation";
import { Chip, dateTime, unitLabel } from "./authoring-shared";
import { ExportControls } from "./export-controls";
import { Modal } from "./modal";
import { panelId, Tabs, tabId } from "./tabs";
import { TeachingNav } from "./teaching-nav";
import { useTeaching } from "./use-teaching";
import styles from "./teaching.module.css";

type Detail = components["schemas"]["ExamDetailDTO"];
type StudentView = components["schemas"]["StudentExamViewDTO"];
type Confirm = "publish" | "archive" | null;
const COGNITIVE: Record<string, string> = { remember: "Nhận biết", understand: "Thông hiểu", apply: "Vận dụng", analyze: "Phân tích" };

export function ExamDetailScreen({ examId }: { examId: string }) {
  const { phase, csrf, workspace, message, handle, reload } = useTeaching();
  const wsBase = workspace ? `/api/backend/workspaces/${workspace.id}` : "";
  const base = wsBase ? `${wsBase}/exams/${examId}` : "";
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(true);
  const [tab, setTab] = useState("teacher");
  const [student, setStudent] = useState<{ versionNo: number; view: StudentView | null; error: string } | null>(null);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    if (!base) return;
    try { setDetail(await read(base)); setError(""); }
    catch (e) { setError(handle(e)); }
    finally { setLoadingDetail(false); }
  }, [base, handle]);
  // Network synchronisation on workspace change.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, [load]);

  const version = detail?.currentVersion || null;
  const versionNo = version?.versionNo ?? null;
  const studentStale = tab === "student" && versionNo !== null && student?.versionNo !== versionNo;
  // The student sheet is always fetched from the student-view endpoint, never derived from the teacher DTO.
  useEffect(() => {
    if (!studentStale || !base || versionNo === null) return;
    let live = true;
    read(`${base}/versions/${versionNo}/student-view`).then(
      (view: StudentView) => { if (live) setStudent({ versionNo, view, error: "" }); },
      (e: unknown) => { if (live) setStudent({ versionNo, view: null, error: handle(e) }); },
    );
    return () => { live = false; };
  }, [studentStale, base, versionNo, handle]);

  async function run(action: "publish" | "archive") {
    if (!version) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await read(action === "publish" ? `${base}/versions/${version.versionNo}/publish` : `${base}/archive`, jsonInit(csrf));
      setStudent(null);
      setNotice(action === "publish" ? "Đã xuất bản đề. Nội dung phiên bản này không thể chỉnh sửa nữa." : "Đã lưu trữ đề.");
      setConfirm(null);
      await load();
    } catch (e) { setError(handle(e)); setConfirm(null); }
    finally { setBusy(false); }
  }

  const status = detail ? EXAM_STATUS[detail.status] : null;
  return <div className={styles.page}><div className={styles.wrap}>
    <TeachingNav current="exams" />
    <Link className={styles.back} href="/dashboard/exams">← Quay lại Đề kiểm tra</Link>
    <section className={styles.card} aria-busy={phase === "loading" || loadingDetail}>
      {phase === "loading" && <p role="status">Đang tải…</p>}
      {phase === "error" && <><p role="alert" className={styles.error}>{message}</p><button className="button button-secondary" onClick={() => void reload()}>Thử lại</button></>}
      {phase === "ready" && loadingDetail && <p role="status">Đang tải đề…</p>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
      {notice && <p role="status" className={styles.notice}>{notice}</p>}
      {detail && status && <>
        <div className={styles.head}><h1>{detail.title}</h1><div className={styles.actions}><Chip label={status[0]} tone={status[1]} />{detail.status === "published" && <Chip label="Đã xuất bản" tone="info" />}</div></div>
        <p className={styles.muted}>{version ? `Phiên bản ${version.versionNo} · ${version.items.length} câu · ${version.totalPoints} điểm · ` : ""}cập nhật {dateTime(detail.updatedAt)}{version?.publishedAt ? ` · xuất bản ${dateTime(version.publishedAt)}` : ""}</p>
        {detail.selectionReport && <p className={styles.muted}>Chọn câu tự động: {detail.selectionReport.selected} câu · seed <code>{detail.selectionReport.seed}</code></p>}
        <div className={styles.toolbar}>
          <div className={styles.actions}>
            <button className="button button-primary" disabled={busy || !version || version.status !== "draft" || detail.status === "archived"} onClick={() => setConfirm("publish")}>Xuất bản</button>
            <button className="button button-secondary" disabled={busy || detail.status === "archived"} onClick={() => setConfirm("archive")}>Lưu trữ</button>
          </div>
        </div>

        {version && <>
          <Tabs prefix="exam" label="Phiên bản đề" tabs={[{ id: "teacher", label: "Bản giáo viên" }, { id: "student", label: "Bản học sinh" }]} active={tab} onChange={setTab} />
          {tab === "teacher" && <div role="tabpanel" id={panelId("exam", "teacher")} aria-labelledby={tabId("exam", "teacher")} className={styles.dialogBody}>
            <p><span className={styles.onlyTeacher}>Chỉ giáo viên</span> <span className={styles.muted}>Cột đáp án và giải thích không xuất hiện trong bản học sinh.</span></p>
            <div className={styles.tableWrap}><table className={styles.table}>
              <caption className="sr-only">Các câu của đề, bản giáo viên</caption>
              <thead><tr><th scope="col">Câu</th><th scope="col">Nội dung</th><th scope="col">Đơn vị / mức</th><th scope="col">Điểm</th><th scope="col">Đáp án đúng (Chỉ giáo viên)</th></tr></thead>
              <tbody>{version.items.slice().sort((a, b) => a.position - b.position).map(item => <tr key={item.id}>
                <td>{item.position}</td>
                <td><p className={styles.stem}>{item.stem}</p>
                  <ul className={styles.choices}>{item.choices.map(c => <li key={c.key} data-correct={c.key === item.correctKey}>{c.key}. {c.text}</li>)}</ul>
                  {item.explanation && <small className={styles.muted}>Giải thích (Chỉ giáo viên): {item.explanation}</small>}</td>
                <td><small>{unitLabel(item.curriculumUnitId)}{item.cognitiveLevel ? ` · ${COGNITIVE[item.cognitiveLevel] || item.cognitiveLevel}` : ""}</small></td>
                <td>{item.points}</td>
                <td><strong>{item.correctKey ?? "—"}</strong></td>
              </tr>)}</tbody>
            </table></div>
          </div>}
          {tab === "student" && <div role="tabpanel" id={panelId("exam", "student")} aria-labelledby={tabId("exam", "student")} className={styles.dialogBody}>
            {(studentStale || !student) && <p role="status">Đang tải bản học sinh…</p>}
            {student && !studentStale && student.error && <p role="alert" className={styles.error}>{student.error}</p>}
            {student?.view && !studentStale && <div className={styles.studentSheet}>
              <h2>{student.view.title}</h2>
              <p className={styles.muted}>Phiên bản {student.view.versionNo} · {student.view.items.length} câu · {student.view.totalPoints} điểm</p>
              <ol>{student.view.items.slice().sort((a, b) => a.position - b.position).map(item => <li key={item.id}>
                <p className={styles.stem}>{item.stem} <small className={styles.muted}>({item.points} điểm)</small></p>
                <ul className={styles.choices}>{item.choices.map(c => <li key={c.key}>{c.key}. {c.text}</li>)}</ul>
              </li>)}</ol>
            </div>}
          </div>}

          <h2>Xuất tệp</h2>
          <p className={styles.muted}>PDF chưa hỗ trợ tiếng Việt, dùng DOCX.</p>
          <ExportControls wsBase={wsBase} csrf={csrf} target={{ examVersionId: version.id }} title={detail.title}
            combos={[{ format: "docx", audience: "teacher" }, { format: "docx", audience: "student" }, { format: "pdf", audience: "teacher" }, { format: "pdf", audience: "student" }]} onError={handle} />
        </>}

        <h2>Các phiên bản</h2>
        <div className={styles.tableWrap}><table className={styles.table}>
          <caption className="sr-only">Lịch sử phiên bản đề</caption>
          <thead><tr><th scope="col">Bản</th><th scope="col">Trạng thái</th><th scope="col">Tổng điểm</th><th scope="col">Xuất bản lúc</th></tr></thead>
          <tbody>{detail.versions.slice().sort((a, b) => b.versionNo - a.versionNo).map(v => <tr key={v.id}>
            <td>{v.versionNo}</td><td><Chip label={EXAM_STATUS[v.status][0]} tone={EXAM_STATUS[v.status][1]} /></td><td>{v.totalPoints}</td><td>{dateTime(v.publishedAt)}</td>
          </tr>)}</tbody>
        </table></div>
      </>}
    </section>
    {confirm === "publish" && <Modal title="Xuất bản đề kiểm tra" onClose={() => !busy && setConfirm(null)}>
      <div className={styles.dialogBody}>
        <p>Sau khi xuất bản, phiên bản {version?.versionNo} của đề sẽ <strong>không thể chỉnh sửa</strong>: danh sách câu hỏi, điểm và đáp án được cố định để bài làm của học sinh luôn chấm theo đúng nội dung này. Muốn thay đổi, bạn cần tạo một đề mới.</p>
        <div className={styles.actions}>
          <button className="button button-primary" disabled={busy} onClick={() => void run("publish")}>{busy ? "Đang xuất bản…" : "Xác nhận xuất bản"}</button>
          <button className="button button-secondary" disabled={busy} onClick={() => setConfirm(null)}>Hủy</button>
        </div>
      </div>
    </Modal>}
    {confirm === "archive" && <Modal title="Lưu trữ đề kiểm tra" onClose={() => !busy && setConfirm(null)}>
      <div className={styles.dialogBody}>
        <p>Đề đã lưu trữ sẽ không thể giao cho lớp mới. Bài đã giao trước đó không bị ảnh hưởng.</p>
        <div className={styles.actions}>
          <button className="button button-primary" disabled={busy} onClick={() => void run("archive")}>{busy ? "Đang lưu trữ…" : "Xác nhận lưu trữ"}</button>
          <button className="button button-secondary" disabled={busy} onClick={() => setConfirm(null)}>Hủy</button>
        </div>
      </div>
    </Modal>}
  </div></div>;
}
