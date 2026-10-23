import { PasswordLogin } from "@/components/auth/password-login";
export default async function Page({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <>{error && <p role="alert">{error === "expired" ? "Phiên đã hết hạn. Vui lòng đăng nhập lại." : "Đăng nhập chưa hoàn tất. Vui lòng thử lại."}</p>}<PasswordLogin google={Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET)} /></>;
}
