import { notFound } from "next/navigation";
import { ClassDetailScreen } from "@/components/teaching/class-detail-screen";
import { pageSession } from "@/lib/server/page-session";
import { isUuid } from "@/lib/server/validation";
export const dynamic = "force-dynamic";
export default async function Page({ params }: { params: Promise<{ classId: string }> }) {
  await pageSession();
  const { classId } = await params;
  if (!isUuid(classId)) notFound();
  return <ClassDetailScreen classId={classId.toLowerCase()} />;
}
