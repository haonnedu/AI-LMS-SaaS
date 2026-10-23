import { mkdirSync } from "node:fs";
import { expect, test } from "@playwright/test";

test("login remains usable on desktop and mobile", async ({ page }) => {
  mkdirSync("evidence/better-auth", { recursive: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Tiếp tục", exact: true })).toBeEnabled();
  await page.screenshot({ path: "evidence/better-auth/login-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "evidence/better-auth/login-mobile.png", fullPage: true });
});
