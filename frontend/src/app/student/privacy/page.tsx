import { StudentPrivacyScreen } from "@/components/student/privacy-screen";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export const metadata = { title: "Dữ liệu của em" };
export default async function Page() { await pageSession(); return <StudentPrivacyScreen />; }
