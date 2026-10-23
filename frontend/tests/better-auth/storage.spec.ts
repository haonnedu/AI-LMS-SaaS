import { createHash, randomUUID } from "node:crypto";
import { test, expect } from "@playwright/test";
import { betterStorage, decryptStorage } from "../../src/lib/server/better-storage";
import { redis } from "../../src/lib/server/session-store";

process.env.SESSION_REDIS_URL = "redis://127.0.0.1:6381/3";
process.env.SESSION_ENCRYPTION_KEY = "c".repeat(64);

test("encrypted Redis sessions have absolute cap and cannot be revived after logout", async () => {
  const key = randomUUID(), value = JSON.stringify({ session: { createdAt: new Date(Date.now() - 86300000).toISOString() }, user: { email: "private@example.test" } });
  await betterStorage.set(key, value, 7200);
  const connection = await redis(), raw = (await connection.get("eduvia:ba:" + key))!;
  expect(raw).not.toContain("private@example.test");
  expect(await betterStorage.get(key)).toBe(value);
  expect(await connection.ttl("eduvia:ba:" + key)).toBeLessThanOrEqual(100);
  expect(() => decryptStorage("other-id", raw)).toThrow();
  await betterStorage.delete(key);
  await betterStorage.set(key, value, 7200);
  expect(await betterStorage.get(key)).toBeNull();
  expect(await connection.exists("eduvia:ba:revoked:" + createHash("sha256").update(key).digest("hex"))).toBe(1);
});

test("one-time proof consumption and rate counters are atomic", async () => {
  const key = randomUUID();
  await betterStorage.set(key, JSON.stringify({ proof: "one-use" }), 300);
  const results = await Promise.all(Array.from({ length: 6 }, () => betterStorage.getAndDelete(key)));
  expect(results.filter(Boolean)).toHaveLength(1);
  const counter = randomUUID();
  const values = await Promise.all(Array.from({ length: 10 }, () => betterStorage.increment(counter, 60)));
  expect(values.sort((a, b) => a - b)).toEqual([1,2,3,4,5,6,7,8,9,10]);
});
