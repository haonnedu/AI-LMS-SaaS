import { LoginScreen } from "@/components/auth/login-screen";
export default async function Page({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <>{error && <p role="alert">{error === "expired" ? "Phiên đã hết hạn. Vui lòng đăng nhập lại." : "Đăng nhập chưa hoàn tất. Vui lòng thử lại."}</p>}<LoginScreen /></>;
}
