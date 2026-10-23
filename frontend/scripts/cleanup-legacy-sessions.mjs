// Operator-only cleanup: the retired SDK used eduvia:session:* and eduvia:verify:*.
import { createClient } from "redis";
const apply = process.argv.includes("--apply");
if (!process.env.SESSION_REDIS_URL) throw new Error("SESSION_REDIS_URL required");
const client = createClient({ url: process.env.SESSION_REDIS_URL, socket: { connectTimeout: 3000, socketTimeout: 3000, reconnectStrategy: false }, commandOptions: { timeout: 3000 } });
client.on("error", () => {});
try {
  await client.connect();
  let matched = 0;
  for (const pattern of ["eduvia:session:*", "eduvia:verify:*"]) for await (const keys of client.scanIterator({ MATCH: pattern, COUNT: 100 })) {
    matched += keys.length;
    if (apply && keys.length) await client.unlink(keys);
  }
  console.log(JSON.stringify({ mode: apply ? "apply" : "dry_run", legacySessions: matched }));
} finally { if (client.isOpen) await client.quit(); }
