import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, ClipboardCheck, GraduationCap, Users } from "lucide-react";
import { PageHeading } from "@/components/page-heading";

export const metadata: Metadata = { title: "My classes" };

export default function ClassesPage() {
  return <><PageHeading eyebrow="EVERY LEARNER, A NEW POSSIBILITY" title="Room for your classroom." description="A clear view of your learners and the work you share." /><section className="empty-panel"><span className="empty-icon"><GraduationCap size={38} strokeWidth={1.4} aria-hidden="true" /></span><span className="pill">YOUR FUTURE CLASSROOM</span><h2>Great things begin with a class.</h2><p>This space is ready for the next stage. Class creation, student invitations, and assignments will become available after accounts and enrollment are implemented.</p><Link href="/settings" className="button button-primary">View workspace setup <ArrowRight size={17} aria-hidden="true" /></Link></section><div className="class-roadmap"><article><span className="tile-icon cool"><Users size={22} aria-hidden="true" /></span><div><span className="eyebrow">COMING IN THE TEACHING PILOT</span><h3>People first</h3><p>Organize classes and enroll students within your workspace.</p></div></article><article><span className="tile-icon warm"><ClipboardCheck size={22} aria-hidden="true" /></span><div><span className="eyebrow">COMING AFTER ENROLLMENT</span><h3>A clearer picture of progress</h3><p>Publish reviewed quizzes and release results when you are ready.</p></div></article></div></>;
}
