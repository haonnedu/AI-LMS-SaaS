import Link from "next/link";
import { AccountScreen } from "@/components/auth/account-screen";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export default async function Page() { await pageSession(); return <><p><Link href="/account">Trung tâm tài khoản</Link></p><AccountScreen mode="dashboard" /></>; }
