import { notFound } from "next/navigation";
import { ExamDetailScreen } from "@/components/teaching/exam-detail-screen";
import { isUuid } from "@/lib/server/validation";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export default async function Page({ params }: { params: Promise<{ examId: string }> }) {
  await pageSession();
  const { examId } = await params;
  if (!isUuid(examId)) notFound();
  return <ExamDetailScreen examId={examId.toLowerCase()} />;
}
