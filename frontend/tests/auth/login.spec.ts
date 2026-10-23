import { test, expect, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { redis } from "../../src/lib/server/session-store";
process.env.SESSION_REDIS_URL = process.env.AUTH_E2E_REDIS_URL || "redis://127.0.0.1:6381/2";
async function login(page: Page, email = `teacher-${Date.now()}@example.com`) {
  await page.goto("/login");
  await page.screenshot({ path: "evidence/auth/login-desktop.png", fullPage: true });
  await page.getByRole("link", { name: "Đăng nhập", exact: true }).click();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("Test-password-123!");
  await page.getByRole("button", { name: "Continue" }).click();
}
test("login, provision, reload, CSRF, logout and protected route", async ({ page }) => {
  await login(page);
  await expect(page).toHaveURL(/onboarding/);
  await page.getByRole("button", { name: "Mở workspace cá nhân" }).click();
  await expect(page).toHaveURL(/dashboard/);
  await expect(page.getByText("Vai trò: owner")).toBeVisible();
  await page.reload();
  await expect(page.getByText("Vai trò: owner")).toBeVisible();
  await page.screenshot({ path: "evidence/auth/dashboard-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.screenshot({ path: "evidence/auth/dashboard-mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.setViewportSize({ width: 1440, height: 900 });
  const cookie = (await page.context().cookies()).find(c => c.name === "eduvia_session");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Lax");
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
  const csrf = await page.request.post("/api/backend/auth/bootstrap");
  expect(csrf.status()).toBe(403);
  expect((await page.request.get("/auth/access-token")).status()).toBe(404);
  expect((await page.request.get("/auth/logout")).status()).toBe(404);
  const session = await (await page.request.get("/api/session")).json();
  expect(JSON.stringify(session)).not.toContain("accessToken");
  await page.getByRole("button", { name: "Đăng xuất", exact: true }).click();
  await expect(page).toHaveURL(/login/);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/login/);
  expect((await (await page.request.get("/api/session")).json()).authenticated).toBe(false);
  const replay = await page.context().browser()!.newContext();
  await replay.addCookies([cookie!]);
  const replayPage = await replay.newPage();
  await replayPage.goto("http://127.0.0.1:3105/dashboard");
  await expect(replayPage).toHaveURL(/login/);
  await replay.close();
});
test("unverified email cannot bootstrap; verified relogin succeeds", async ({ page, request }) => {
  const email = `unverified-${Date.now()}@example.com`;
  await login(page, email);
  await expect(page).toHaveURL(/verify-email/);
  expect((await page.request.post("/api/backend/auth/bootstrap")).status()).toBe(403);
  await request.post("http://127.0.0.1:9101/verify", { data: { email } });
  await page.getByRole("link", { name: "Tôi đã xác minh — đăng nhập lại" }).click();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("Test-password-123!");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/onboarding/);
});
test("invalid callback and external return URL are rejected", async ({ page }) => {
  await page.goto("/auth/callback?code=forged&state=forged");
  await expect(page).toHaveURL(/login\?error=callback/);
  await page.goto("/auth/login?returnTo=https://attacker.invalid&redirect_uri=https://attacker.invalid");
  expect(new URL(page.url()).searchParams.get("redirect_uri")).toBe("http://127.0.0.1:3105/auth/callback");
});
test("concurrent API calls refresh once", async ({ page, request }) => {
  const before = await (await request.get("http://127.0.0.1:9101/stats")).json();
  await login(page, `refresh-${Date.now()}@example.com`);
  await expect(page).toHaveURL(/onboarding/);
  await page.waitForTimeout(3000);
  const session = await (await page.request.get("/api/session")).json();
  const responses = await Promise.all([1,2].map(() => page.request.post("/api/backend/auth/bootstrap", { headers: { Origin: "http://127.0.0.1:3105", "X-CSRF-Token": session.csrfToken } })));
  expect(responses.map(r => r.status())).toEqual([200,200]);
  const after = await (await request.get("http://127.0.0.1:9101/stats")).json();
  expect(after.refreshes - before.refreshes).toBe(1);
});


test("verification resend uses session identity, CSRF and cooldown", async ({ page, request }) => {
  const before = await (await request.get("http://127.0.0.1:9101/stats")).json();
  await login(page, `unverified-resend-${Date.now()}@example.com`);
  await expect(page).toHaveURL(/verify-email/);
  const session = await (await page.request.get("/api/session")).json();
  const headers = { Origin: "http://127.0.0.1:3105", "X-CSRF-Token": session.csrfToken };
  expect((await page.request.post("/api/auth/resend-verification")).status()).toBe(403);
  // Submitted identities are ignored: only the session's subject can receive a job.
  expect((await page.request.post("/api/auth/resend-verification", { headers, data: { user_id: "attacker" } })).status()).toBe(202);
  expect((await page.request.post("/api/auth/resend-verification", { headers })).status()).toBe(429);
  const after = await (await request.get("http://127.0.0.1:9101/stats")).json();
  expect(after.verificationEmails - before.verificationEmails).toBe(1);
});

test("logout clears another open authenticated tab", async ({ page, context }) => {
  await login(page);
  await expect(page).toHaveURL(/onboarding/);
  await page.getByRole("button", { name: "Mở workspace cá nhân" }).click();
  await expect(page).toHaveURL(/dashboard/);
  await expect(page.getByText("Vai trò: owner")).toBeVisible();
  const second = await context.newPage();
  await second.goto("/dashboard");
  await expect(second.getByText("Vai trò: owner")).toBeVisible();
  await page.getByRole("button", { name: "Đăng xuất", exact: true }).click();
  await expect(page).toHaveURL(/login/);
  await expect(second).toHaveURL(/login/);
  await second.close();
});


test("verification email hourly quota is enforced", async ({ page }) => {
  const email = `unverified-quota-${Date.now()}@example.com`;
  await login(page, email);
  await expect(page).toHaveURL(/verify-email/);
  const session = await (await page.request.get("/api/session")).json();
  const digest = createHash("sha256").update("http://localhost:9101:auth0|" + email).digest("hex");
  const key = "eduvia:verify:" + digest;
  const now = Date.now();
  await (await redis()).zAdd(key, [1,2,3,4,5].map(i => ({ score: now-i*61000, value: String(now-i*61000) })));
  try {
    expect((await page.request.post("/api/auth/resend-verification", { headers: { Origin: "http://127.0.0.1:3105", "X-CSRF-Token": session.csrfToken } })).status()).toBe(429);
  } finally { await (await redis()).del(key); }
});

test("expired server session redirects to login", async ({ page }) => {
  const connection = await redis();
  const previous = new Set(await connection.keys("eduvia:session:*"));
  await login(page);
  await expect(page).toHaveURL(/onboarding/);
  const created = (await connection.keys("eduvia:session:*")).filter(key => !previous.has(key));
  expect(created).toHaveLength(1);
  await connection.del(created);
  await page.reload();
  await expect(page).toHaveURL(/login/);
});

test("Redis interruption returns bounded 503 and recovers without mock", async ({ page }) => {
  await login(page);
  await expect(page).toHaveURL(/onboarding/);
  await expect(page.getByRole("button", { name: "Mở workspace cá nhân" })).toBeEnabled();
  await (await redis()).sendCommand(["CLIENT", "PAUSE", "4500", "ALL"]);
  const response = await page.request.get("/api/session");
  expect(response.status()).toBe(503);
  expect((await response.json()).error.code).toBe("service_unavailable");
  await expect.poll(async () => {
    const retry = await page.request.get("/api/session");
    return retry.status() === 200 && (await retry.json()).authenticated;
  }).toBe(true);
});

test("signup uses hosted form and wrong password stays at provider", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("link", { name: "Tạo tài khoản", exact: true }).click();
  expect(new URL(page.url()).searchParams.get("screen_hint")).toBe("signup");
  await page.getByLabel("Email", { exact: true }).fill("wrong@example.com");
  await page.getByLabel("Password", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Invalid credentials")).toBeVisible();
  expect((await (await page.request.get("/api/session")).json()).authenticated).toBe(false);
});
