"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpRight, BookOpen, ChevronRight, Home, Library, Settings2, Sprout, Users } from "lucide-react";

const links = [
  { href: "/", label: "Overview", icon: Home },
  { href: "/library", label: "Knowledge library", icon: Library },
  { href: "/classes", label: "My classes", icon: Users },
  { href: "/settings", label: "Workspace settings", icon: Settings2 },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const currentPage = links.find((link) => link.href === pathname)?.label ?? "Workspace";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className="sidebar">
        <Link href="/" className="brand" aria-label="Eduvia home">
          <span className="brand-mark"><BookOpen size={23} strokeWidth={1.8} aria-hidden="true" /></span>
          <span>eduvia<span className="brand-dot">.</span></span>
        </Link>
        <div className="workspace-card">
          <span className="workspace-avatar"><Sprout size={20} aria-hidden="true" /></span>
          <div><strong>Teaching workspace</strong><span>Personal · Preview</span></div>
        </div>
        <p className="nav-label">YOUR WORKSPACE</p>
        <nav aria-label="Main navigation" className="main-nav">
          {links.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} className={`nav-link ${pathname === href ? "active" : ""}`} aria-current={pathname === href ? "page" : undefined}>
              <Icon size={19} strokeWidth={1.8} aria-hidden="true" /><span>{label}</span>
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="small-note"><span className="note-symbol">✦</span><p>A little less admin.<br /><strong>A little more teaching.</strong></p></div>
          <Link href="/settings" className="sidebar-footer">Workspace setup <ArrowUpRight size={16} aria-hidden="true" /></Link>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><ChevronRight size={14} aria-hidden="true" /><strong>{currentPage}</strong></div>
          <span className="preview-label"><span aria-hidden="true" />Foundation preview</span>
        </header>
        <main id="main-content" className="page-content" tabIndex={-1}>{children}</main>
        <footer className="page-footer"><span>Made for the way teachers work.</span><span>Eduvia <span aria-hidden="true">·</span> 0.1.0</span></footer>
      </div>
    </div>
  );
}
