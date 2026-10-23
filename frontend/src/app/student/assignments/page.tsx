import { StudentAssignmentsScreen } from "@/components/student/assignments-screen";
import { pageSession } from "@/lib/server/page-session";
export const dynamic = "force-dynamic";
export default async function Page() { await pageSession(); return <StudentAssignmentsScreen />; }
