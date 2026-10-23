import { defineConfig } from "@playwright/test";
// Existing native local services only. Never resets databases or launches fixtures.
export default defineConfig({
  preserveOutput: "always", testDir: "./tests/local-auth", timeout: 90000, expect: { timeout: 15000 }, workers: 1,
  use: { baseURL: "http://127.0.0.1:3000", headless: true, trace: "off" },
});
