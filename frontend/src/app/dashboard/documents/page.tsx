import { DocumentsScreen } from "@/components/teaching/documents-screen";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export default async function Page() { await pageSession(); return <DocumentsScreen />; }
