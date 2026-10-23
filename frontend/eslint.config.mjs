import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTypescript,
  globalIgnores([".next/**", ".next-auth-test/**", "test-results/**", "playwright-report/**", "out/**", "next-env.d.ts", "src/lib/api/generated.ts"]),
]);
