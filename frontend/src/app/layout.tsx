import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import { AuthProvider } from "@/components/auth/auth-provider";
import "./globals.css";
import "./ui-system.css";
import "./redesign.css";
export const metadata: Metadata = {
  title: { default: "Eduvia · Không gian giảng dạy", template: "%s · Eduvia" },
  description: "Không gian cho giáo viên, học liệu và những bài học đầy cảm hứng.",
  icons: { icon: "/eduvia-mark.svg" },
  robots: { index: false, follow: false },
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="vi"><body><AuthProvider><AppShell>{children}</AppShell></AuthProvider></body></html>;
}
