import { notFound, redirect } from "next/navigation";
import { JoinScreen } from "@/components/teaching/join-screen";
import { HttpError, requireSession } from "@/lib/server/auth";
import { isInviteToken } from "@/lib/server/validation";
export const dynamic = "force-dynamic";
export const metadata = { referrer: "no-referrer" };
export default async function Page({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  if (!isInviteToken(token)) notFound();
  try { await requireSession(); }
  catch (error) {
    if (error instanceof HttpError && error.status === 401) redirect("/login?returnTo=" + encodeURIComponent("/join/" + token));
    if (error instanceof HttpError && error.code === "email_unverified") redirect("/verify-email");
    throw error;
  }
  return <JoinScreen token={token} />;
}
