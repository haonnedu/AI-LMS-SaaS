import { expect, test } from "@playwright/test";
import { resetRates } from "./reset-rates";
test.beforeEach(resetRates);
import { createClient } from "redis";

test("rejects external callbacks, forged Origin and unverified Google email", async ({ page, request }) => {
  expect((await request.post("/api/auth/sign-in/social", { headers: { Origin: "http://127.0.0.1:3106" }, data: { provider: "google", callbackURL: "https://attacker.example" } })).status()).toBe(400);
  expect((await request.post("/api/auth/sign-in/email", { headers: { Origin: "https://attacker.example" }, data: { email: "none@example.test", password: "password" } })).status()).toBe(403);
  await request.post("http://127.0.0.1:9112/identity", { data: { sub: "unverified-google", email: "unverified-google@example.test", email_verified: false } });
  await page.route("https://accounts.google.com/**", async route => {
    const url = new URL(route.request().url()), response = await request.get("http://127.0.0.1:9112/authorize" + url.search, { maxRedirects: 0 });
    await route.fulfill({ status: 302, headers: { Location: response.headers().location }, body: "" });
  });
  await page.goto("/login");
  await page.getByRole("button", { name: "Đăng nhập bằng Google", exact: true }).click();
  await expect.poll(async () => (await (await page.request.get("/api/session")).json()).authenticated).toBe(false);
  expect((await page.request.get("/api/backend/me")).status()).toBe(401);
});

test("Google-first account cannot unlink its final method; Redis expiry removes access", async ({ page, request, context }) => {
  const email = `google-first-${Date.now()}@example.test`;
  await request.post("http://127.0.0.1:9112/identity", { data: { sub: email, email, email_verified: true } });
  await page.route("https://accounts.google.com/**", async route => {
    const url = new URL(route.request().url()), response = await request.get("http://127.0.0.1:9112/authorize" + url.search, { maxRedirects: 0 });
    await route.fulfill({ status: 302, headers: { Location: response.headers().location }, body: "" });
  });
  await page.goto("/login");
  await page.getByRole("button", { name: "Đăng nhập bằng Google", exact: true }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByRole("button", { name: "Mở workspace cá nhân" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/account");
  await expect(page.getByRole("button", { name: "Hủy liên kết Google và đăng xuất" })).toBeDisabled();
  await expect(page.getByText("Email và mật khẩu: Chưa thiết lập")).toBeVisible();
  const original = await (await page.request.get("/api/backend/me")).json();
  await page.getByRole("button", { name: "Thiết lập mật khẩu qua email" }).click();
  await expect(page.getByRole("status")).toContainText("Đã gửi hướng dẫn");
  const messages: string[] = await (await request.get("http://127.0.0.1:9112")).json();
  const decoded = messages.filter(m => m.includes(email)).at(-1)!.replace(/=\r?\n/g, "").replace(/=([0-9A-F]{2})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
  await page.goto(decoded.match(/http:\/\/127\.0\.0\.1:3106\/api\/auth\/reset-password[^\s<>]*/)![0]);
  await page.getByLabel("Mật khẩu", { exact: true }).fill("Google-first-password-2026!");
  await page.getByRole("button", { name: "Tiếp tục", exact: true }).click();
  await expect(page.getByText("Đã đặt mật khẩu. Vui lòng đăng nhập lại.")).toBeVisible();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Mật khẩu", { exact: true }).fill("Google-first-password-2026!");
  await page.getByRole("button", { name: "Tiếp tục", exact: true }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByRole("button", { name: "Mở workspace cá nhân" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  expect((await (await page.request.get("/api/backend/me")).json()).id).toBe(original.id);
  const cookie = (await context.cookies()).find(cookie => cookie.name.endsWith(".session_token"))!;
  const token = decodeURIComponent(cookie.value).split(".")[0];
  const connection = createClient({ url: "redis://127.0.0.1:6381/3" });
  await connection.connect();
  try { expect(await connection.expire("eduvia:ba:" + token, 1)).toBe(1); await expect.poll(async () => (await (await page.request.get("/api/session")).json()).authenticated).toBe(false); }
  finally { await connection.close(); }
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
});
