import "server-only";
import { createHash } from "node:crypto";
import { headers } from "next/headers";
import { better, authDatabase } from "./better-auth";
import { HttpError, requireSession } from "./auth";
import { redis } from "./session-store";

export function accountKey(user: string, action: string) { return "eduvia:account:" + action + ":" + createHash("sha256").update(user).digest("hex"); }
export async function methods(user: string) {
  const result = await authDatabase().query('SELECT id,"providerId",(password IS NOT NULL) AS password FROM auth.account WHERE "userId"=$1', [user]);
  return { password: result.rows.some(row => row.providerId === "credential" && row.password), google: result.rows.some(row => row.providerId === "google"), googleAccountId: result.rows.find(row => row.providerId === "google")?.id as string | undefined };
}
export async function requireRecent() {
  const session = await requireSession();
  const fresh = await (await redis()).get(accountKey(session.user.sub, "reauth"));
  if (fresh !== session.eduviaId) throw new HttpError(403, "reauthentication_required", "Vui lòng xác thực lại bằng mật khẩu.");
  return session;
}
export async function markSecurityChange(userId: string) {
  await authDatabase().query("INSERT INTO auth.session_revocations(user_id,revoked_before) VALUES($1,$2) ON CONFLICT(user_id) DO UPDATE SET revoked_before=GREATEST(auth.session_revocations.revoked_before,excluded.revoked_before)", [userId, new Date()]);
}
export async function revokeAll(userId?: string) {
  const subject = userId || (await requireSession()).user.sub;
  await markSecurityChange(subject);
  await (await redis()).set("eduvia:ba:user-revoked-before:" + createHash("sha256").update(subject).digest("hex"), String(Date.now()), { EX: 86400 });
  await better().api.revokeSessions({ headers: await headers() });
  return better().api.signOut({ headers: await headers(), asResponse: true });
}
