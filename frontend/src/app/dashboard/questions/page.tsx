import { QuestionsScreen } from "@/components/teaching/questions-screen";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export default async function Page({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  await pageSession();
  const { status } = await searchParams;
  return <QuestionsScreen initialStatus={status === "draft" || status === "active" || status === "retired" ? status : ""} />;
}
