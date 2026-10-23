import { expect, test } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { writeFileSync } from "node:fs";

test("email signup, verification, password reset, workspace and logout use Better Auth", async ({ page, request }, testInfo) => {
  const email = `local-smoke-${Date.now()}@example.test`, password = randomBytes(24).toString("base64url"), replacement = randomBytes(24).toString("base64url");
  const origin = "http://127.0.0.1:3000";
  const post = (path: string, data: unknown) => request.post("/api/auth/" + path, { headers: { Origin: origin }, data });
  const signup = await post("sign-up/email", { email, password, name: "Teacher", callbackURL: "/login" });
  expect(signup.status()).toBe(200);
  expect(await signup.json()).not.toHaveProperty("token");
  expect((await request.post("/api/backend/auth/bootstrap", { headers: { Origin: origin } })).status()).toBe(401);
  const blocked = await post("sign-in/email", { email, password });
  expect(blocked.status()).toBe(403);
  async function mailLink(fragment: string) {
    let url = "";
    await expect.poll(async () => {
      const inbox = await (await request.get("http://127.0.0.1:8025/api/v1/messages")).json();
      for (const item of inbox.messages || []) {
        if (!item.To?.some((to: { Address: string }) => to.Address === email)) continue;
        const message = await (await request.get("http://127.0.0.1:8025/api/v1/message/" + item.ID)).json();
        const candidate = String(message.Text || "").match(/http:\/\/127\.0\.0\.1:3000\/[^\s<>]+/g)?.find(link => link.includes(fragment));
        if (candidate) { url = candidate; break; }
      }
      return url;
    }).not.toBe("");
    return url;
  }
  await page.goto(await mailLink("verify-email"));
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Mật khẩu", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Tiếp tục", exact: true }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByRole("button", { name: "Mở workspace cá nhân" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const originalUser = await (await page.request.get("/api/backend/me")).json();
  const originalWorkspaces = await (await page.request.get("/api/backend/workspaces")).json();
  await page.reload();
  await expect(page.getByText("Vai trò: owner")).toBeVisible();
  const session = await (await page.request.get("/api/session")).json();
  expect(session.authenticated).toBe(true);
  expect(session).not.toHaveProperty("token");
  for (const path of ["/api/auth/token", "/api/auth/get-session", "/auth/access-token"]) expect((await page.request.get(path)).status()).toBe(404);
  expect((await page.request.post("/api/logout", { headers: { Origin: origin } })).status()).toBe(403);
  await page.goto("/account");
  await expect(page.getByText("Email và mật khẩu: Đã thiết lập")).toBeVisible();
  await page.getByRole("button", { name: "Đặt lại mật khẩu qua email" }).click();
  await page.goto(await mailLink("reset-password"));
  await expect(page).toHaveURL(/\/reset-password/);
  await page.getByLabel("Mật khẩu", { exact: true }).fill(replacement);
  await page.getByRole("button", { name: "Tiếp tục", exact: true }).click();
  await expect(page.getByText("Đã đặt mật khẩu. Vui lòng đăng nhập lại.")).toBeVisible();
  expect((await post("sign-in/email", { email, password })).status()).toBe(401);
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Mật khẩu", { exact: true }).fill(replacement);
  await page.getByRole("button", { name: "Tiếp tục", exact: true }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByRole("button", { name: "Mở workspace cá nhân" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  expect((await (await page.request.get("/api/backend/me")).json()).id).toBe(originalUser.id);
  expect((await (await page.request.get("/api/backend/workspaces")).json()).items[0].id).toBe(originalWorkspaces.items[0].id);
  await page.getByRole("button", { name: "Đăng xuất", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goBack();
  await page.reload();
  expect((await page.request.get("/api/backend/me")).status()).toBe(401);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
  const sanitizedEvidence = JSON.stringify({ type: "automated-native-local", emailDelivery: "Mailpit only", userId: originalUser.id, workspaceId: originalWorkspaces.items[0].id, checks: ["signup", "unverified blocked", "Mailpit verification", "login", "bootstrap", "reload", "account center", "Mailpit reset", "old password rejected", "same user/workspace", "logout/back/reload denied"] });
  const evidencePath = testInfo.outputPath("sanitized-local-evidence.json");
  writeFileSync(evidencePath, sanitizedEvidence);
  await testInfo.attach("sanitized-local-evidence", { contentType: "application/json", path: evidencePath });
});
