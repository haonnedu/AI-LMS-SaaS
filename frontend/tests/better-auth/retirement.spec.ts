import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { createClient } from "redis";

test("operator cleanup deletes only retired namespaces and defaults to dry-run", async () => {
  const url = "redis://127.0.0.1:6381/3", client = createClient({ url });
  await client.connect();
  const retired = ["eduvia:session:retirement-fixture", "eduvia:verify:retirement-fixture"];
  const keep = ["eduvia:ba:retirement-fixture", "eduvia:lock:retirement-fixture", "other:retirement-fixture"];
  try {
    for (const key of [...retired, ...keep]) await client.set(key, "fixture", { EX: 60 });
    const run = (apply: boolean) => JSON.parse(execFileSync(process.execPath, ["scripts/cleanup-legacy-sessions.mjs", ...(apply ? ["--apply"] : [])], { env: { ...process.env, SESSION_REDIS_URL: url }, encoding: "utf8", timeout: 10000 }));
    expect(run(false).mode).toBe("dry_run");
    for (const key of retired) expect(await client.exists(key)).toBe(1);
    expect(run(true).legacySessions).toBe(2);
    for (const key of retired) expect(await client.exists(key)).toBe(0);
    for (const key of keep) expect(await client.get(key)).toBe("fixture");
    expect(run(true).legacySessions).toBe(0);
  } finally { await client.del([...retired, ...keep]); await client.close(); }
});
