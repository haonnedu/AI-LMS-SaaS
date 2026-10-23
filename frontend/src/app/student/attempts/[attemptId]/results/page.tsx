import { notFound } from "next/navigation";
import { ResultsScreen } from "@/components/student/results-screen";
import { pageSession } from "@/lib/server/page-session";
import { isUuid } from "@/lib/server/validation";
export const dynamic = "force-dynamic";
export default async function Page({ params }: { params: Promise<{ attemptId: string }> }) {
  await pageSession();
  const { attemptId } = await params;
  if (!isUuid(attemptId)) notFound();
  return <ResultsScreen attemptId={attemptId.toLowerCase()} />;
}
