import { QuestionsScreen } from "@/components/teaching/questions-screen";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export default async function Page() { await pageSession(); return <QuestionsScreen />; }
