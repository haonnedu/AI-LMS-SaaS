import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/better-auth", timeout: 90000, expect: { timeout: 15000 }, workers: 1,
  use: { baseURL: "http://127.0.0.1:3106", headless: true, trace: "retain-on-failure" },
  webServer: [
    { command: "node tests/better-auth/services.mjs legacy", url: "http://localhost:9101/.well-known/openid-configuration", timeout: 30000 },
    { command: "node tests/better-auth/services.mjs mail", url: "http://127.0.0.1:9112", timeout: 30000 },
    { command: "node tests/better-auth/services.mjs api", url: "http://127.0.0.1:8006/health/live", timeout: 30000 },
    { command: "node tests/better-auth/services.mjs frontend", url: "http://127.0.0.1:3106/login", timeout: 120000 },
  ],
});
