import { notFound } from "next/navigation";
import { betterEnabled } from "@/lib/server/better-auth";
import { pageSession } from "@/lib/server/page-session";
import { MigrationScreen } from "@/components/auth/migration-screen";
export const dynamic = "force-dynamic";
export default async function Page() {
  if (!betterEnabled() || process.env.AUTH0_MIGRATION_ENABLED !== "1") notFound();
  await pageSession();
  return <MigrationScreen />;
}
