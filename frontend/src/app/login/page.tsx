import { PasswordLogin } from "@/components/auth/password-login";
import { ReturnToStash } from "@/components/auth/return-to-stash";
import { safeJoinReturnTo } from "@/lib/server/validation";
export default async function Page({ searchParams }: { searchParams: Promise<{ error?: string; returnTo?: string }> }) {
  const { error, returnTo } = await searchParams;
  const safe = safeJoinReturnTo(returnTo);
  return <>{error && <p role="alert">{error === "expired" ? "Phiên đã hết hạn. Vui lòng đăng nhập lại." : "Đăng nhập chưa hoàn tất. Vui lòng thử lại."}</p>}{safe && <ReturnToStash value={safe} />}<PasswordLogin google={Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET)} /></>;
}
