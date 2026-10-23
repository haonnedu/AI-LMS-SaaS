import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import type { SessionData } from "@auth0/nextjs-auth0/types";
import { sessionStore, redis, withSessionLock } from "../../src/lib/server/session-store";

process.env.SESSION_REDIS_URL = process.env.AUTH_E2E_REDIS_URL || "redis://127.0.0.1:6381/2";
process.env.SESSION_ENCRYPTION_KEY = "c".repeat(64);
function record(createdAt = Math.floor(Date.now() / 1000)): SessionData {
  return { user: { sub: "fixture-user" }, tokenSet: { accessToken: "sensitive-test-token", expiresAt: createdAt + 300 }, internal: { sid: randomUUID(), createdAt } };
}
test("encrypted session and atomic update cannot resurrect logout", async () => {
  const id = randomUUID();
  const value = record();
  await sessionStore.set(id, value);
  const connection = await redis();
  const raw = await connection.get("eduvia:session:" + id);
  expect(raw).not.toContain("sensitive-test-token");
  expect(await sessionStore.get(id)).toEqual(value);
  await sessionStore.delete(id);
  expect(await sessionStore.update!(id, value)).toBe(false);
  expect(await sessionStore.get(id)).toBeNull();
});
test("idle TTL never extends beyond the absolute lifetime", async () => {
  const id = randomUUID();
  await sessionStore.set(id, record(Math.floor(Date.now() / 1000) - 86300));
  const ttl = await (await redis()).ttl("eduvia:session:" + id);
  expect(ttl).toBeGreaterThan(0);
  expect(ttl).toBeLessThanOrEqual(100);
  await sessionStore.delete(id);
  await sessionStore.set(id, record(Math.floor(Date.now() / 1000) - 86401));
  expect(await sessionStore.get(id)).toBeNull();
});
test("session lock serializes competing updates", async () => {
  const id = randomUUID();
  let running = 0;
  let maximum = 0;
  await Promise.all([1,2,3].map(() => withSessionLock(id, async () => {
    running++; maximum = Math.max(maximum, running);
    await new Promise(resolve => setTimeout(resolve, 30));
    running--;
  })));
  expect(maximum).toBe(1);
});


test("encrypted records cannot be substituted across session IDs", async () => {
  const first = randomUUID(), second = randomUUID();
  await sessionStore.set(first, record());
  const connection = await redis();
  await connection.set("eduvia:session:" + second, (await connection.get("eduvia:session:" + first))!, { EX: 60 });
  try { await expect(sessionStore.get(second)).rejects.toThrow(); }
  finally { await connection.del(["eduvia:session:" + first, "eduvia:session:" + second]); }
});
