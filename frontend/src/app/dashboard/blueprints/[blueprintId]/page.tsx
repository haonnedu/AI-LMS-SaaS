import { notFound } from "next/navigation";
import { BlueprintDetailScreen } from "@/components/teaching/blueprint-detail-screen";
import { isUuid } from "@/lib/server/validation";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export default async function Page({ params }: { params: Promise<{ blueprintId: string }> }) {
  await pageSession();
  const { blueprintId } = await params;
  if (!isUuid(blueprintId)) notFound();
  return <BlueprintDetailScreen blueprintId={blueprintId.toLowerCase()} />;
}
