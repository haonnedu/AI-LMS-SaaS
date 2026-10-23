import { notFound } from "next/navigation";
import { betterEnabled } from "@/lib/server/better-auth";
import { pageSession } from "@/lib/server/page-session";
import { AccountCenter } from "@/components/auth/account-center";
export const dynamic = "force-dynamic";
export default async function Page() { if (!betterEnabled()) notFound(); await pageSession(); return <AccountCenter />; }
