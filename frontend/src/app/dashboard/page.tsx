import Link from "next/link";
import { betterEnabled } from "@/lib/server/better-auth";
import { AccountScreen } from "@/components/auth/account-screen";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export default async function Page() { await pageSession(); return <>{betterEnabled() && <p><Link href="/account">Trung tâm tài khoản</Link></p>}<AccountScreen mode="dashboard" /></>; }
