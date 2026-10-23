import { notFound } from "next/navigation";
import { AssignmentsScreen } from "@/components/teaching/assignments-screen";
import { pageSession } from "@/lib/server/page-session";
import { isUuid } from "@/lib/server/validation";
export const dynamic = "force-dynamic";
export default async function Page({ params }: { params: Promise<{ classId: string }> }) {
  await pageSession();
  const { classId } = await params;
  if (!isUuid(classId)) notFound();
  return <AssignmentsScreen classId={classId.toLowerCase()} />;
}
