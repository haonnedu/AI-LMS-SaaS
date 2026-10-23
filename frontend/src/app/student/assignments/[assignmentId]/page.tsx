import { notFound } from "next/navigation";
import { StudentAssignmentScreen } from "@/components/student/assignment-screen";
import { pageSession } from "@/lib/server/page-session";
import { isUuid } from "@/lib/server/validation";
export const dynamic = "force-dynamic";
export default async function Page({ params }: { params: Promise<{ assignmentId: string }> }) {
  await pageSession();
  const { assignmentId } = await params;
  if (!isUuid(assignmentId)) notFound();
  return <StudentAssignmentScreen assignmentId={assignmentId.toLowerCase()} />;
}
