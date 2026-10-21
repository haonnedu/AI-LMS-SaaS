"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, ClipboardList, FileText, Users, X } from "lucide-react";

export type FlowSelection = {
  kind: "class" | "assessment";
  title: string;
  count?: number;
  progress?: number;
  status?: string;
  student?: boolean;
};

export function FlowDialog({ selection, onClose }: { selection: FlowSelection; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [tab, setTab] = useState("Tổng quan");
  const [reviewed, setReviewed] = useState(false);
  const isClass = selection.kind === "class";
  const tabs = isClass ? selection.student ? ["Tổng quan", "Học liệu"] : ["Tổng quan", "Học liệu", "Thành viên"] : ["Tổng quan", "Câu hỏi", "Bài nộp"];

  useEffect(() => {
    const node = ref.current;
    const oldOverflow = document.body.style.overflow;
    const previous = document.activeElement as HTMLElement | null;
    node?.showModal();
    document.body.style.overflow = "hidden";
    return () => { node?.close(); document.body.style.overflow = oldOverflow; previous?.focus(); };
  }, []);

  return <dialog ref={ref} className="modal flow-dialog" aria-labelledby="flow-title" onCancel={onClose} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="section-heading"><span className="badge green">{isClass ? "Lớp học" : "Bài kiểm tra"} · Dữ liệu minh họa</span><button className="icon-button" aria-label="Đóng chi tiết" onClick={onClose}><X size={21} /></button></div>
    <h2 id="flow-title">{selection.title}</h2>
    <div className="flow-meta"><span className="badge neutral">Học kỳ I · 2026–2027</span><span className="badge gold">{isClass ? selection.student ? "Không gian học sinh" : "Không gian giáo viên" : selection.status}</span></div>
    <div className="tabs flow-tabs" aria-label="Nội dung chi tiết">{tabs.map(t => <button key={t} aria-pressed={tab === t} className={tab === t ? "selected" : ""} onClick={() => setTab(t)}>{t}</button>)}</div>
    {tab === "Tổng quan" && <>
      <div className="flow-summary">{(isClass ? [[String(selection.count), "Học sinh mẫu"], [`${selection.progress}%`, "Hoàn thành bài gần nhất"], ["HK I", "Học kỳ hiện tại"]] : [["10", "Câu một đáp án"], ["15 phút", "Thời lượng mẫu"], ["10 điểm", "Thang điểm"]]).map(([value, label]) => <div key={label}><strong>{value}</strong><span>{label}</span></div>)}</div>
      <div className="info-note"><ClipboardList size={20} /><p>{isClass ? selection.student ? "Học liệu được giáo viên chia sẻ sẽ có trong lớp. Tiến độ tại đây là số liệu minh họa." : "Học liệu, thành viên và tiến độ được nhóm theo lớp. Lớp vừa tạo có 0 học sinh cho đến khi có người tham gia." : "Giáo viên kiểm tra nội dung và đáp án trước khi giao bài. Đáp án chỉ hiển thị ở giao diện giáo viên; học sinh xem kết quả theo quy tắc công bố."}</p></div>
      <div className="document-actions"><button className="button button-secondary" onClick={() => setTab(isClass ? selection.student ? "Học liệu" : "Thành viên" : "Câu hỏi")}>{isClass ? <Users size={17} /> : <FileText size={17} />}{isClass ? selection.student ? "Xem học liệu lớp" : "Xem thành viên mẫu" : "Duyệt câu hỏi mẫu"}</button>{selection.student ? <button className="button button-primary" onClick={onClose}>Quay lại góc học tập <ArrowRight size={16} /></button> : <Link className="button button-primary" href={isClass ? "/assessments" : "/analytics"}>{isClass ? "Đến bài tập & kiểm tra" : "Đến kết quả học tập"}<ArrowRight size={16} /></Link>}</div>
    </>}
    {tab === "Học liệu" && <><h3>Nguồn học tập trong lớp</h3><p className="form-hint">Các học liệu đã được giáo viên duyệt sẽ xuất hiện tại đây.</p>{selection.student ? <div className="info-note"><FileText size={20} /><p>Giáo viên chưa chia sẻ học liệu thực tế trong bản mẫu này.</p></div> : <Link href="/library" className="button button-secondary"><FileText size={17} />Khám phá thư viện</Link>}</>}
    {tab === "Thành viên" && (selection.count === 0 ? <div className="empty-results"><Users size={32} /><h3>Lớp học đang chờ những thành viên đầu tiên.</h3><p>Luồng mời học sinh sẽ được mở khi kết nối tài khoản.</p></div> : <><p className="form-hint">Hiển thị 3 hồ sơ giả định để minh họa bố cục, không phải danh sách đầy đủ.</p><div className="table-scroll"><table><thead><tr><th>HỌC SINH</th><th>TRẠNG THÁI BÀI MẪU</th></tr></thead><tbody>{["01", "02", "03"].map((n, i) => <tr key={n}><td>Học sinh minh họa {n}</td><td><span className={`badge ${i === 2 ? "gold" : "green"}`}>{i === 2 ? "Chưa nộp" : "Đã nộp"}</span></td></tr>)}</tbody></table></div></>)}
    {tab === "Câu hỏi" && <><span className="badge neutral">Câu 1/10 · Chỉ minh họa một câu</span><h3 className="question-heading">Đồ thị hàm số y = x² có dạng nào?</h3><ol className="review-options">{["Đường thẳng", "Parabol", "Đường tròn", "Elip"].map((o, i) => <li key={o} className={i === 1 ? "correct" : ""}><span>{String.fromCharCode(65 + i)}</span>{o}{i === 1 && <Check size={16} aria-label="Đáp án đúng" />}</li>)}</ol><p className="form-hint">Giải thích mẫu: đồ thị hàm số bậc hai là một parabol. Đây là nội dung mẫu, chưa đối chiếu chương trình.</p><button className="button button-primary" onClick={() => setReviewed(true)}><Check size={17} />{reviewed ? "Đã xem câu hỏi mẫu" : "Đánh dấu đã xem câu mẫu"}</button>{reviewed && <p role="status" className="form-hint">Đã đánh dấu trong phiên xem. Bài kiểm tra chưa được xuất bản.</p>}</>}
    {tab === "Bài nộp" && <div className="empty-results"><ClipboardList size={32} /><h3>Chưa kết nối bài nộp thực tế</h3><p>Dữ liệu trên dashboard đang là minh họa. Sau khi giao bài thực tế, kết quả sẽ xuất hiện tại đây.</p><Link href="/analytics" className="button button-secondary">Xem bố cục báo cáo mẫu <ArrowRight size={16} /></Link></div>}
  </dialog>;
}
