import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, BookOpen, FolderLock, Library, ShieldCheck } from "lucide-react";
import { PageHeading } from "@/components/page-heading";

export const metadata: Metadata = { title: "Knowledge library" };

export default function LibraryPage() {
  return <><PageHeading eyebrow="BUILT ON WHAT YOU KNOW" title="Your knowledge library." description="Give every lesson a trusted starting point." /><section className="empty-panel"><span className="empty-icon"><Library size={36} strokeWidth={1.4} aria-hidden="true" /></span><span className="pill">YOUR FUTURE LIBRARY</span><h2>A good lesson starts with good sources.</h2><p>Your documents and teaching materials will come together here. Uploads and search will be available after workspace accounts and private storage are connected.</p><Link href="/settings" className="button button-primary">View workspace setup <ArrowRight size={17} aria-hidden="true" /></Link></section><section className="principle-grid" aria-label="Knowledge library design"><article><FolderLock size={22} aria-hidden="true" /><h3>A private space</h3><p>Your personal materials belong to your workspace. Joining a school will not automatically share them.</p></article><article><BookOpen size={22} aria-hidden="true" /><h3>Knowledge with context</h3><p>Shared resources will carry source and license information, with access checked before use.</p></article><article><ShieldCheck size={22} aria-hidden="true" /><h3>Always your review</h3><p>AI drafts will point back to their sources, ready for your judgment before publication.</p></article></section></>;
}
