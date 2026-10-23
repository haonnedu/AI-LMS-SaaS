import { redirect } from "next/navigation";
import { AccountScreen } from "@/components/auth/account-screen";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export default async function Page() {
  const session = await pageSession(false);
  if (session.user.email_verified === true) redirect("/onboarding");
  return <AccountScreen mode="verify" />;
}
