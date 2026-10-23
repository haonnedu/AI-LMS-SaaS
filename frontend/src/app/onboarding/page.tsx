import { pageSession } from "@/lib/server/page-session";
import { AccountScreen } from "@/components/auth/account-screen";
export const dynamic = "force-dynamic";
export default async function Page() { await pageSession(); return <AccountScreen mode="onboarding" />; }
