import { redirect } from "next/navigation";
import { HttpError, requireSession } from "./auth";
export async function pageSession(verified = true) {
  try { return await requireSession(verified); }
  catch (error) {
    if (error instanceof HttpError && error.status === 401) redirect("/login");
    if (error instanceof HttpError && error.code === "email_unverified") redirect("/verify-email");
    throw error;
  }
}
