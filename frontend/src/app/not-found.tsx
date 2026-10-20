import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export default function NotFound() {
  return <section className="empty-panel"><p className="eyebrow">PAGE NOT FOUND</p><h1>A small detour.</h1><p>This page is not part of your workspace. Let’s get you back to the overview.</p><Link href="/" className="button button-primary"><ArrowLeft size={17} aria-hidden="true" />Back to overview</Link></section>;
}
