import { pageSession } from "@/lib/server/page-session";
import { AccountCenter } from "@/components/auth/account-center";
export const dynamic = "force-dynamic";
export default async function Page() { await pageSession(); return <AccountCenter />; }
