import { betterEnabled } from "@/lib/server/better-auth";
import { PasswordLogin } from "@/components/auth/password-login";
import { redirect } from "next/navigation";
import { AccountScreen } from "@/components/auth/account-screen";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export default async function Page() {
  if (betterEnabled()) return <PasswordLogin initialMode="verify" />;
  const session = await pageSession(false);
  if (session.user.email_verified === true) redirect("/onboarding");
  return <AccountScreen mode="verify" />;
}
