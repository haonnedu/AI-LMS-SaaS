import Link from "next/link";
import { ArrowRight, BookOpen, Check, FileText, FolderOpen, Sparkles, Users } from "lucide-react";
import { PageHeading } from "@/components/page-heading";
import { ServiceStatus } from "@/components/service-status";

const steps = [
  { title: "Bring your knowledge", text: "Start with the material you know and trust.", icon: BookOpen },
  { title: "Shape a lesson", text: "Turn your sources into a draft you can make your own.", icon: Sparkles },
  { title: "Teach with confidence", text: "Review every detail before it reaches your students.", icon: Check },
];

export default function OverviewPage() {
  return (
    <>
      <PageHeading eyebrow="A LITTLE SPACE TO DO GREAT THINGS" title="Welcome to your workspace." description="Your knowledge, your classroom, and your next great lesson — together." />
      <section className="hero-grid" aria-labelledby="hero-heading">
        <div className="hero-card">
          <div className="hero-copy"><span className="hero-tag"><Sparkles size={14} aria-hidden="true" />Thoughtfully built for teachers</span><h2 id="hero-heading">More room<br />for the <em>teaching.</em></h2><p>A home for the materials and ideas that make your classroom yours.</p><Link className="button button-light" href="/library">Explore your library <ArrowRight size={17} aria-hidden="true" /></Link></div>
          <div className="lesson-art" aria-hidden="true"><div className="art-circle" /><div className="art-spark">✦</div><div className="art-sheet"><div className="art-sheet-top"><BookOpen size={24} /><span>LESSON NOTES</span></div><div className="art-line wide" /><div className="art-line" /><div className="art-separator" /><div className="art-check"><span><Check size={12} /></span>Start with a spark</div><div className="art-check"><span><Check size={12} /></span>Make it your own</div><div className="art-check"><span><Check size={12} /></span>Bring it to life</div></div><div className="art-pill"><Sparkles size={15} />Your expertise. Amplified.</div></div>
        </div>
        <div className="workflow-card"><p className="eyebrow">THE EDUVIA APPROACH</p><h2>From an idea<br />to an “I get it.”</h2><ol className="workflow-list">{steps.map(({ title, text, icon: Icon }, index) => <li key={title}><span className="workflow-icon"><Icon size={18} aria-hidden="true" /></span><div><span className="step-number">0{index + 1}</span><h3>{title}</h3><p>{text}</p></div></li>)}</ol><span className="muted-label">The teaching workflow ahead</span></div>
      </section>
      <section className="workspace-section" aria-labelledby="workspace-heading"><div className="section-heading"><h2 id="workspace-heading">Make yourself at home</h2><span>A fresh start</span></div><div className="resource-grid">
        <Link href="/library" className="resource-card"><span className="tile-icon warm"><FolderOpen size={23} aria-hidden="true" /></span><div><h3>Your knowledge library</h3><p>A space for trusted sources and teaching materials.</p><span className="card-link">Take a look <ArrowRight size={15} aria-hidden="true" /></span></div></Link>
        <Link href="/classes" className="resource-card"><span className="tile-icon cool"><Users size={23} aria-hidden="true" /></span><div><h3>Your classroom, connected</h3><p>A home for classes, learners, and their next steps.</p><span className="card-link">Explore classes <ArrowRight size={15} aria-hidden="true" /></span></div></Link>
      </div></section>
      <section className="foundation-section" aria-labelledby="foundation-heading"><div className="foundation-note"><FileText size={20} aria-hidden="true" /><div><h2 id="foundation-heading">The foundation is taking shape</h2><p>This preview includes the workspace and API connection. Accounts, saved materials, and classroom tools are the next milestones.</p></div></div><ServiceStatus /></section>
    </>
  );
}
