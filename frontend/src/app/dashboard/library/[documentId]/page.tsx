import { notFound } from "next/navigation";
import { LibraryDetailScreen } from "@/components/teaching/library-detail-screen";
import { isUuid } from "@/lib/server/validation";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export default async function Page({ params }: { params: Promise<{ documentId: string }> }) {
  await pageSession();
  const { documentId } = await params;
  if (!isUuid(documentId)) notFound();
  return <LibraryDetailScreen documentId={documentId.toLowerCase()} />;
}
