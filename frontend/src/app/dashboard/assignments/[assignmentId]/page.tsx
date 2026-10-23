import { notFound } from "next/navigation";
import { AssignmentDetailScreen } from "@/components/teaching/assignment-detail-screen";
import { pageSession } from "@/lib/server/page-session";
import { isUuid } from "@/lib/server/validation";
export const dynamic = "force-dynamic";
export default async function Page({ params }: { params: Promise<{ assignmentId: string }> }) {
  await pageSession();
  const { assignmentId } = await params;
  if (!isUuid(assignmentId)) notFound();
  return <AssignmentDetailScreen assignmentId={assignmentId.toLowerCase()} />;
}
