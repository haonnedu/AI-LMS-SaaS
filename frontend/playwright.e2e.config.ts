import { defineConfig } from "@playwright/test";
// PILOT-01 journey against an already-running full stack (frontend 3000, API 8000, worker --beat,
// MinIO, fake LLM). Skipped unless EDUVIA_E2E=1; never starts services itself.
export default defineConfig({
  testDir: "./tests/e2e", timeout: 120000, expect: { timeout: 15000 }, workers: 1,
  use: { baseURL: process.env.EDUVIA_E2E_BASE_URL || "http://127.0.0.1:3000", headless: true, viewport: { width: 1440, height: 900 }, trace: "retain-on-failure" },
});
