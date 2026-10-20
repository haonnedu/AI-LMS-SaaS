import { cp } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
for (const [source, destination] of [
  ["public", ".next/standalone/public"],
  [".next/static", ".next/standalone/.next/static"],
]) {
  await cp(path.join(root, source), path.join(root, destination), { recursive: true });
}
console.log("Prepared standalone assets.");
