import Link from "next/link";
import { betterEnabled } from "@/lib/server/better-auth";
import { AccountScreen } from "@/components/auth/account-screen";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export default async function Page() { await pageSession(); return <>{betterEnabled() && process.env.AUTH0_MIGRATION_ENABLED === "1" && <p>Đã có tài khoản trước đây? <Link href="/account/migrate">Chuyển tài khoản cũ để giữ workspace</Link> trước khi mở workspace mới.</p>}<AccountScreen mode="onboarding" /></>; }
