import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
try {
  process.loadEnvFile(path.join(root, ".env.local"));
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
const server = spawn(process.execPath, [path.join(root, ".next/standalone/server.js")], {
  cwd: root,
  stdio: "inherit",
  env: { ...process.env, HOSTNAME: "127.0.0.1", PORT: process.env.PORT ?? "3000" },
});
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.kill(signal));
}
server.on("error", (error) => {
  console.error("Could not start the standalone server:", error.message);
  process.exitCode = 1;
});
server.on("exit", (code) => { process.exitCode = code ?? 0; });
