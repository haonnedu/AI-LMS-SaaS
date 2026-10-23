import { notFound } from "next/navigation";
import { LessonEditorScreen } from "@/components/teaching/lesson-editor-screen";
import { isUuid } from "@/lib/server/validation";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export default async function Page({ params }: { params: Promise<{ itemId: string }> }) {
  await pageSession();
  const { itemId } = await params;
  if (!isUuid(itemId)) notFound();
  return <LessonEditorScreen itemId={itemId.toLowerCase()} />;
}
