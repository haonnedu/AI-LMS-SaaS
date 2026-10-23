import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/auth", timeout: 60000, expect: { timeout: 15000 }, workers: 1,
  use: { baseURL: "http://127.0.0.1:3105", headless: true, viewport: { width: 1440, height: 900 }, trace: "retain-on-failure" },
  // "auth" keeps the existing suite unchanged; "e2e" is the PILOT-01 journey, skipped unless EDUVIA_E2E=1.
  projects: [{ name: "auth", testDir: "./tests/auth" }, { name: "e2e", testDir: "./tests/e2e" }],
  webServer: [
    { command: "node tests/auth/start-service.mjs oidc", url: "http://127.0.0.1:9101/.well-known/openid-configuration", timeout: 30000 },
    { command: "node tests/auth/start-service.mjs api", url: "http://127.0.0.1:8005/health/live", timeout: 30000 },
    { command: "node tests/auth/start-service.mjs frontend", url: "http://127.0.0.1:3105/login", timeout: 120000 },
  ],
});
