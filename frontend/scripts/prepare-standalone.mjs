import { cp } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = process.env.AUTH_TEST_MODE === "1" ? ".next-auth-test" : ".next";
for (const [source, destination] of [
  ["public", `${dist}/standalone/public`],
  [`${dist}/static`, `${dist}/standalone/${dist}/static`],
]) {
  await cp(path.join(root, source), path.join(root, destination), { recursive: true });
}
console.log("Prepared standalone assets.");
