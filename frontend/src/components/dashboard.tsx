"use client";

import Link from "next/link";
import { useAuth } from "@/components/auth/auth-provider";
import { useWorkspace } from "@/components/workspace/workspace-provider";
import workspaceStyles from "@/components/workspace/workspace.module.css";
import { useState } from "react";
import { ArrowDownToLine, ArrowRight, ArrowUpRight, BookOpen, CalendarDays, Check, ClipboardList, Clock3, FileText, Plus, Sparkles, Users } from "lucide-react";

const resources = [
  { title: "Hàm số bậc hai và đồ thị", type: "Giáo án", tone: "green", subject: "Toán học · Lớp 10" },
  { title: "Bài tập phương trình bậc hai", type: "Bài tập", tone: "gold", subject: "Toán học · Lớp 10" },
  { title: "Chuyển động thẳng biến đổi đều", type: "Tài liệu", tone: "blue", subject: "Vật lý · Lớp 10" },
];

export function Dashboard({ onOpenMaterial }: { onOpenMaterial: (title: string) => void }) {
  const [day, setDay] = useState(21);
  const { session } = useAuth();
  const { workspace } = useWorkspace();
  return <div className="dashboard-v2">
    <header className="dashboard-welcome"><div><span className="overline">KHÔNG GIAN GIẢNG DẠY / TỔNG QUAN</span><h1>Chào {session?.user.name ?? "bạn"}<span className="greeting-spark" aria-hidden="true">✳</span></h1><p>Cùng tạo nên một ngày học thật ý nghĩa.</p></div><Link className="button button-primary" href="/lessons"><Plus size={18} />Tạo học liệu</Link></header>
    {session && !workspace && <section className={workspaceStyles.reminder} aria-label="Hoàn thành onboarding"><div><strong>Không gian cá nhân mẫu đang chờ bạn</strong><p>Hoàn thành bước chuẩn bị để xem workspace trong phiên này.</p></div><Link href="/onboarding" className="button button-secondary">Hoàn thành onboarding</Link></section>}
    {workspace && <p className="form-hint">{workspace.name} · Dữ liệu minh họa · <Link href="/onboarding" className="text-link">Xem không gian mẫu</Link></p>}
    <section className="dashboard-v2-hero"><div className="hero-v2-copy"><span className="hero-v2-label"><span />EDUVIA AI · ĐỒNG HÀNH CÙNG GIÁO VIÊN</span><h2>Dạy hay hơn.<br /><span>Nhẹ việc hơn.</span></h2><p>Từ kiến thức của bạn đến bài học truyền cảm hứng.<br />Để AI giúp bạn chuẩn bị phần còn lại.</p><Link href="/lessons" className="button hero-v2-button">Soạn bài cùng AI <ArrowUpRight size={18} /></Link></div><div className="hero-v2-art" aria-hidden="true"><div className="orbit-v2 one" /><div className="orbit-v2 two" /><div className="orbit-v2 three" /><span className="hero-v2-star">✳</span><div className="floating-note"><Sparkles size={18} /><span>Ý tưởng của bạn.<br /><strong>Khả năng mới.</strong></span></div></div><span className="hero-v2-number" aria-hidden="true">01 / CREATE</span></section>
    <section className="dashboard-v2-stats" aria-label="Số liệu không gian minh họa">{[
      { label: "Lớp đang giảng dạy", value: "03", note: "Học kỳ I · 2026–2027", Icon: Users, bars: [12, 19, 15, 27, 23, 34, 40] },
      { label: "Lượt ghi danh", value: "112", note: "Tổng lượt ghi danh trong 3 lớp", Icon: BookOpen, bars: [12, 20, 16, 29, 25, 35, 43] },
      { label: "Học liệu trong thư viện", value: "04", note: "Tài liệu minh họa", Icon: FileText, bars: [10, 13, 20, 16, 30, 35, 43] },
      { label: "Bản nháp cần xem", value: "01", note: "Đề kiểm tra 15 phút", Icon: ClipboardList, bars: [30, 24, 29, 20, 17, 12, 9] },
    ].map(({ label, value, note, Icon, bars }, index) => <article className={`metric-v2 metric-${index}`} key={label}><div className="metric-label"><span>{label}</span><Icon size={18} /></div><div className="metric-value"><strong>{value}</strong><span className="metric-bars" aria-hidden="true">{bars.map((height, i) => <i key={i} style={{ height }} />)}</span></div><p>{note}</p></article>)}</section>
    <section className="workspace-tools" aria-labelledby="tools-title"><div className="v2-section-title"><h2 id="tools-title">Bạn muốn bắt đầu từ đâu?</h2><span>Công cụ giảng dạy</span></div><div className="tool-grid-v2">{[
      { label: "Soạn giáo án", detail: "Từ ý tưởng đến bài giảng", href: "/lessons", Icon: Sparkles, tone: "lime" },
      { label: "Tạo bài kiểm tra", detail: "Đánh giá đúng trọng tâm", href: "/assessments", Icon: ClipboardList, tone: "peach" },
      { label: "Thêm học liệu", detail: "Xây thư viện của riêng bạn", href: "/library", Icon: ArrowDownToLine, tone: "lavender" },
    ].map(({ label, detail, href, Icon, tone }) => <Link href={href} className={`tool-v2 ${tone}`} key={href}><span className="tool-v2-icon"><Icon size={23} /></span><div><h3>{label}</h3><p>{detail}</p></div><ArrowUpRight size={19} className="tool-v2-arrow" /></Link>)}</div></section>
    <div className="dashboard-v2-lower"><section className="v2-schedule"><div className="v2-section-title"><div><span className="overline">MỖI NGÀY, MỘT BƯỚC TIẾN</span><h2>Lịch dạy của bạn</h2></div><span className="schedule-month"><CalendarDays size={16} />10 / 2026</span></div><div className="week-v2" aria-label="Chọn ngày xem lịch">{["T2", "T3", "T4", "T5", "T6", "T7", "CN"].map((label, i) => <button key={label} className={day === 19 + i ? "selected" : ""} aria-pressed={day === 19 + i} onClick={() => setDay(19 + i)}><span>{label}</span><strong>{19 + i}</strong><i /></button>)}</div><div className="schedule-v2-day"><h3>{day === 21 ? "Hôm nay" : `Ngày ${day}/10`} <span>· {day === 21 ? "2 tiết học" : "Chưa có lịch mẫu"}</span></h3><span className="badge neutral">Minh họa</span></div>{day === 21 ? <div className="timeline-v2">{[
      { time: "08:00", end: "08:45", name: "Hàm số bậc hai", cls: "Toán 10A1", room: "A.201", tone: "lime" },
      { time: "09:00", end: "09:45", name: "Luyện tập chương II", cls: "Toán 10A2", room: "A.203", tone: "peach" },
    ].map(item => <Link href="/classes" key={item.time} className={`timeline-v2-item ${item.tone}`}><div className="timeline-v2-time"><strong>{item.time}</strong><span>{item.end}</span></div><div className="timeline-v2-copy"><span>{item.cls} <i />Phòng {item.room}</span><h3>{item.name}</h3><p><Clock3 size={13} />45 phút</p></div><ArrowUpRight size={18} /></Link>)}</div> : <div className="schedule-v2-empty"><CalendarDays size={28} /><p>Ngày này chưa có tiết dạy trong dữ liệu mẫu.</p></div>}<Link className="schedule-v2-footer" href="/classes">Xem tất cả lớp học <ArrowRight size={16} /></Link></section>
      <section className="v2-tasks"><div className="v2-section-title"><h2>Cần bạn xem lại</h2><span className="task-count-v2">02</span></div><Link className="task-v2" href="/assessments"><span className="task-v2-icon peach"><ClipboardList size={21} /></span><div><span className="task-v2-status">BẢN NHÁP AI</span><h3>Kiểm tra 15 phút · Chương II</h3><p>Toán 10A1 · Chờ giáo viên duyệt</p></div><ArrowUpRight size={17} /></Link><Link className="task-v2" href="/analytics"><span className="task-v2-icon lavender"><Check size={21} /></span><div><span className="task-v2-status">KẾT QUẢ HỌC TẬP</span><h3>Ôn tập mệnh đề và tập hợp</h3><p>Toán 10A2 · 26/36 bài nộp mẫu</p></div><ArrowUpRight size={17} /></Link><div className="teacher-note-v2"><Sparkles size={23} /><h3>Chuyên môn là của bạn.<br />Thêm thời gian cũng vậy.</h3><p>Chuẩn bị bài học tiếp theo với một người đồng hành mới.</p><Link href="/lessons">Khám phá trợ lý AI <ArrowRight size={15} /></Link><span aria-hidden="true">✳</span></div></section></div>
    <section className="v2-resources"><div className="v2-section-title"><div><span className="overline">TIẾP TỤC CÔNG VIỆC CỦA BẠN</span><h2>Học liệu gần đây</h2></div><Link href="/library">Mở thư viện <ArrowRight size={16} /></Link></div><div className="v2-resource-list">{resources.map((resource, i) => <button key={resource.title} onClick={() => onOpenMaterial(resource.title)}><span className="resource-index">0{i + 1}</span><span className={`doc-icon ${resource.tone}`}><FileText size={21} /></span><span className="resource-v2-name"><strong>{resource.title}</strong><small>{resource.subject}</small></span><span className={`badge ${resource.tone}`}>{resource.type}</span><span className="resource-v2-date">21/10/2026</span><ArrowUpRight size={19} /></button>)}</div></section>
  </div>;
}
