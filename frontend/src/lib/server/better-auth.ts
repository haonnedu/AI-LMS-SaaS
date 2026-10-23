import "server-only";
import { createHash } from "node:crypto";
import { APIError } from "better-auth/api";
import { betterAuth } from "better-auth";
import { nextCookies } from "better-auth/next-js";
import { jwt } from "better-auth/plugins";
import { Pool } from "pg";
import nodemailer from "nodemailer";
import { betterStorage, encryptStorage } from "./better-storage";
export { decryptStorage } from "./better-storage";
import { redis } from "./session-store";

export function origin() {
  const configured = process.env.APP_BASE_URL;
  if (!configured) throw new Error("app_origin_unconfigured");
  const url = new URL(configured);
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash || !["http:", "https:"].includes(url.protocol)) throw new Error("invalid_app_origin");
  if (process.env.NODE_ENV === "production" && url.protocol !== "https:" && !["127.0.0.1", "localhost"].includes(url.hostname)) throw new Error("https_required");
  return url.origin;
}
let instance: ReturnType<typeof createBetterAuth> | undefined;
let pool: Pool | undefined;
export function authDatabase() {
  if (!process.env.AUTH_DATABASE_URL) throw new Error("auth_database_unconfigured");
  const url = new URL(process.env.AUTH_DATABASE_URL);
  if (url.username !== "eduvia_auth_runtime") throw new Error("restricted_auth_role_required");
  return pool ??= new Pool({ connectionString: url.href, options: "-c search_path=auth,pg_catalog", max: 5, connectionTimeoutMillis: 3000, statement_timeout: 5000 });
}
async function sendMail(to: string, subject: string, url: string) {
  if (!process.env.SMTP_URL || !process.env.AUTH_EMAIL_FROM) throw new Error("email_unconfigured");
  const parsed = new URL(url);
  if (parsed.origin !== origin()) throw new Error("invalid_email_callback");
  const smtp = new URL(process.env.SMTP_URL);
  if (!["smtp:", "smtps:"].includes(smtp.protocol)) throw new Error("invalid_smtp_url");
  const transport = nodemailer.createTransport({ host: smtp.hostname, port: Number(smtp.port || (smtp.protocol === "smtps:" ? 465 : 587)), secure: smtp.protocol === "smtps:", requireTLS: process.env.NODE_ENV === "production", connectionTimeout: 4000, greetingTimeout: 4000, socketTimeout: 5000,
    ...(smtp.username ? { auth: { user: decodeURIComponent(smtp.username), pass: decodeURIComponent(smtp.password) } } : {}) });
  await transport.sendMail({ from: process.env.AUTH_EMAIL_FROM, to, subject, text: `Eduvia\n\n${url}\n\nNếu bạn không yêu cầu thao tác này, hãy bỏ qua email.` });
}
function createBetterAuth() {
  if (!process.env.BETTER_AUTH_SECRET || process.env.BETTER_AUTH_SECRET.length < 32) throw new Error("auth_secret_unconfigured");
  return betterAuth({
    appName: "Eduvia", baseURL: origin(), basePath: "/api/auth", secret: process.env.BETTER_AUTH_SECRET,
    database: authDatabase(), trustedOrigins: [origin()],
    advanced: { useSecureCookies: origin().startsWith("https:"), cookiePrefix: "eduvia_ba", defaultCookieAttributes: { httpOnly: true, sameSite: "lax" } },
    secondaryStorage: betterStorage,
    session: { expiresIn: 7200, updateAge: 60, freshAge: 300, cookieCache: { enabled: false }, storeSessionInDatabase: false },
    emailAndPassword: {
      enabled: true, requireEmailVerification: true, minPasswordLength: 12, maxPasswordLength: 128,
      revokeSessionsOnPasswordReset: true,
      onPasswordReset: async ({ user }) => { const { markSecurityChange } = await import("./account-center"); await markSecurityChange(user.id); await (await redis()).set("eduvia:ba:user-revoked-before:" + createHash("sha256").update(user.id).digest("hex"), String(Date.now()), { EX: 86400 }); },
      sendResetPassword: async ({ user, url }) => sendMail(user.email, "Đặt lại mật khẩu Eduvia", url),
    },
    emailVerification: { sendOnSignUp: true, autoSignInAfterVerification: false, expiresIn: 3600,
      sendVerificationEmail: async ({ user, url }) => sendMail(user.email, "Xác minh email Eduvia", url) },
    socialProviders: process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET ? {
      google: { clientId: process.env.GOOGLE_CLIENT_ID, clientSecret: process.env.GOOGLE_CLIENT_SECRET, prompt: "select_account", mapProfileToUser: async profile => {
        if (profile.email_verified !== true) throw new APIError("FORBIDDEN", { code: "email_unverified", message: "Vui lòng dùng Google đã xác minh email." });
        return { emailVerified: true };
      } },
    } : {},
    account: { storeAccountCookie: false, storeStateStrategy: "database", encryptOAuthTokens: true,
      accountLinking: { enabled: true, disableImplicitLinking: true, allowDifferentEmails: false, allowUnlinkingAll: false } },
    databaseHooks: { account: {
      create: { before: async (account, context) => {
        if (account.providerId === "google") {
          const { accountKey, methods } = await import("./account-center");
          const existing = await methods(account.userId);
          if (existing.google) throw new Error("identity_conflict");
          if (existing.password) {
            const connection = await redis();
            const approved = await connection.getDel(accountKey(account.userId, "approved"));
            if (approved !== account.accountId) {
              if (!context?.headers) throw new Error("link_proof_required");
              const current = await better().api.getSession({ headers: context.headers });
              const intent = await connection.getDel(accountKey(account.userId, "link"));
              const recent = await connection.get(accountKey(account.userId, "reauth"));
              if (!current || current.user.id !== account.userId || intent !== current.session.id || recent !== current.session.id) throw new Error("link_proof_required");
              const pendingKey = accountKey(account.userId, "pending");
              await connection.set(pendingKey, encryptStorage(pendingKey, JSON.stringify({ accountId: account.accountId, sessionId: current.session.id })), { EX: 300 });
              // Do not attach yet. The callback returns to an explicit confirmation page.
              return false;
            }
          }
        }
        return { data: { ...account, accessToken: null, refreshToken: null, idToken: null } };
      } },
      update: { before: async account => ({ data: { ...account, accessToken: null, refreshToken: null, idToken: null } }) },
    } },
    rateLimit: { enabled: true, storage: "secondary-storage", window: 60, max: 30,
      customRules: { "/sign-in/email": { window: 60, max: 5 }, "/sign-up/email": { window: 60, max: 3 }, "/request-password-reset": { window: 60, max: 1 }, "/send-verification-email": { window: 60, max: 1 } } },
    plugins: [jwt({ disableSettingJwtHeader: true,
      jwks: { keyPairConfig: { alg: "RS256", modulusLength: 2048 }, rotationInterval: 2592000, gracePeriod: 600 },
      jwt: { issuer: origin(), audience: process.env.BETTER_AUTH_AUDIENCE || "https://eduvia-api", expirationTime: "5m",
        definePayload: ({ user }) => ({ "https://eduvia.app/claims/email": user.email, "https://eduvia.app/claims/email_verified": user.emailVerified, "https://eduvia.app/claims/name": user.name }) },
    }), nextCookies()],
    logger: { disabled: true },
  });
}
export function better() { return instance ??= createBetterAuth(); }
