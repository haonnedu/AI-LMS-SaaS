import { notFound } from "next/navigation";
import { PasswordLogin } from "@/components/auth/password-login";
import { betterEnabled } from "@/lib/server/better-auth";
export const dynamic = "force-dynamic";
export default function Page() { if (!betterEnabled()) notFound(); return <PasswordLogin initialMode="reset" />; }
