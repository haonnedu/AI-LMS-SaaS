"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, ChevronDown, ChevronRight, LayoutDashboard, Library, Users, Settings2, Sparkles, ClipboardList, ChartNoAxesCombined, GraduationCap, Building2, ShieldCheck, Menu, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
const links = [
  { href: "/", label: "Tổng quan", icon: LayoutDashboard },
  { href: "/library", label: "Thư viện học liệu", icon: Library },
  { href: "/lessons", label: "Soạn bài cùng AI", icon: Sparkles },
  { href: "/classes", label: "Lớp học của tôi", icon: Users },
  { href: "/assessments", label: "Bài tập & kiểm tra", icon: ClipboardList },
  { href: "/analytics", label: "Kết quả học tập", icon: ChartNoAxesCombined },
];
const spaces = [
  { href: "/student", label: "Góc học sinh", icon: GraduationCap },
  { href: "/school", label: "Không gian nhà trường", icon: Building2 },
  { href: "/admin", label: "Quản trị nền tảng", icon: ShieldCheck },
];
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // Real student pages (/student/...) bring their own mobile-first shell; /student itself stays the demo preview.
  const standalone = ["/login", "/onboarding", "/verify-email", "/dashboard"].includes(pathname) || pathname.startsWith("/student/");
  const [menu, setMenu] = useState({ pathname, open: false });
  const open = menu.pathname === pathname && menu.open;
  // Reset route-owned menu state before children mount on the new route.
  if (menu.pathname !== pathname) setMenu({ pathname, open: false });
  const setOpen = (value: boolean) => setMenu({ pathname, open: value });
  const sidebar = useRef<HTMLElement>(null);
  const alternate = spaces.find(space => space.href === pathname);
  const roleLabel = alternate?.label ?? "Không gian giáo viên";
  const visibleLinks = alternate ? [alternate] : links;
  useEffect(() => {
    if (!open || standalone) return;
    const previous = document.activeElement as HTMLElement | null;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebar.current?.querySelector<HTMLElement>("a")?.focus();
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMenu({ pathname, open: false });
      if (event.key !== "Tab") return;
      const controls = Array.from(sidebar.current?.querySelectorAll<HTMLElement>("a, button, summary") ?? []).filter(el => el.getClientRects().length);
      const first = controls[0]; const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    document.addEventListener("keydown", handleKey);
    return () => { document.body.style.overflow = oldOverflow; document.removeEventListener("keydown", handleKey); previous?.focus(); };
  }, [open, pathname, standalone]);
  const currentPage = [...links, ...spaces, { href: "/settings", label: "Cài đặt" }].find((link) => link.href === pathname)?.label ?? "Eduvia";
  if (standalone) return <main className="auth-root">{children}</main>;
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Đến nội dung chính</a>
    {open && <button className="nav-scrim" aria-label="Đóng menu" onClick={() => setOpen(false)} />}
    <aside ref={sidebar} id="workspace-navigation" className={`sidebar ${open ? "is-open" : ""}`} aria-label="Điều hướng không gian">
      <Link href="/" aria-label="Eduvia · Trang tổng quan" className="brand" onClick={() => setOpen(false)}><span className="brand-mark"><BookOpen size={24} /></span><span>eduvia<span className="brand-dot">.</span></span></Link>
      <div className="workspace-card"><span className="workspace-avatar">{alternate ? "DEMO" : "GV"}</span><div><strong>{roleLabel}</strong><span>Dữ liệu minh họa</span></div></div>
      <p className="nav-label">{alternate ? "KHÔNG GIAN HIỆN TẠI" : "GIẢNG DẠY"}</p>
      <nav className="main-nav" aria-label="Điều hướng chính">{visibleLinks.map(({ href, label, icon: Icon }) => <Link key={href} href={href} aria-label={label} title={label} onClick={() => setOpen(false)} className={`nav-link ${pathname === href ? "active" : ""}`} aria-current={pathname === href ? "page" : undefined}><Icon size={19} /><span>{label}</span>{href === "/lessons" && <span className="ai-mini">AI</span>}</Link>)}</nav>
      <details className="role-picker"><summary>Xem giao diện vai trò khác <ChevronDown size={14} aria-hidden="true" /></summary><p className="nav-label">BẢN MẪU · KHÔNG ĐỔI QUYỀN</p><nav aria-label="Khám phá vai trò mẫu">{[{ href: "/", label: "Không gian giáo viên", icon: BookOpen }, ...spaces].map(({ href, label, icon: Icon }) => <Link key={href} href={href} aria-label={label} title={label} onClick={() => setOpen(false)} className="nav-link"><Icon size={18} /><span>{label}</span></Link>)}</nav></details>
      <div className="sidebar-bottom">{!alternate && <Link href="/settings" onClick={() => setOpen(false)} aria-label="Cài đặt không gian" title="Cài đặt không gian" className={`nav-link ${pathname === "/settings" ? "active" : ""}`} aria-current={pathname === "/settings" ? "page" : undefined}><Settings2 size={19} />Cài đặt không gian</Link>}<Link href="/dashboard" aria-label="Mở tài khoản Eduvia" className="profile" onClick={() => setOpen(false)}><span className="avatar">EV</span><span><strong>Tài khoản Eduvia</strong><small>Đăng nhập hoặc mở workspace</small></span><ChevronRight size={16} /></Link></div>
    </aside>
    <div className="workspace-main"><header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-toggle" aria-expanded={open} aria-controls="workspace-navigation" aria-label={open ? "Đóng menu" : "Mở menu"} onClick={() => setOpen(!open)}>{open ? <X size={20} /> : <Menu size={20} />}</button><span>Không gian làm việc</span><ChevronRight size={14} /><strong>{currentPage}</strong></div><span className="preview-label"><span />Bản mẫu tương tác</span></header><main id="main-content" className="page-content" tabIndex={-1}>{children}</main><footer className="page-footer"><span>Mỗi bài học hay bắt đầu từ người thầy.</span><span>Eduvia · Dữ liệu minh họa</span></footer></div>
  </div>;
}
