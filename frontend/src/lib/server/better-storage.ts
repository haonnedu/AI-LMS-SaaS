import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";
import { redis } from "./session-store";
function encryptionKey() {
  const key = process.env.SESSION_ENCRYPTION_KEY;
  if (!key || !/^[a-f0-9]{64}$/i.test(key)) throw new Error("session_key_unconfigured");
  return Buffer.from(key, "hex");
}
export function encryptStorage(key: string, value: string) {
  const iv = randomBytes(12), cipher = createCipheriv("aes-256-gcm", encryptionKey(), iv);
  cipher.setAAD(Buffer.from(key));
  return Buffer.concat([iv, cipher.update(value), cipher.final()]).toString("base64") + "." + cipher.getAuthTag().toString("base64");
}
export function decryptStorage(key: string, value: string) {
  const [data, tag] = value.split("."), packed = Buffer.from(data, "base64");
  const cipher = createDecipheriv("aes-256-gcm", encryptionKey(), packed.subarray(0, 12));
  cipher.setAAD(Buffer.from(key)); cipher.setAuthTag(Buffer.from(tag, "base64"));
  return Buffer.concat([cipher.update(packed.subarray(12)), cipher.final()]).toString();
}
export const betterStorage = {
      async getAndDelete(key: string) { const value = await (await redis()).getDel("eduvia:ba:" + key); return value ? decryptStorage(key, value) : null; },
      async increment(key: string, ttl: number) { return Number(await (await redis()).eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n", { keys: ["eduvia:ba:counter:" + key], arguments: [String(ttl)] })); },
      async get(key: string) { const value = await (await redis()).get("eduvia:ba:" + key); return value ? decryptStorage(key, value) : null; },
      async set(key: string, value: string, ttl?: number) {
        const payload = JSON.parse(value) as { session?: { createdAt: string } } | unknown;
        let expires = ttl || 7200;
        if (payload && typeof payload === "object" && "session" in payload && payload.session) {
          const created = new Date((payload.session as { createdAt: string }).createdAt).getTime();
          expires = Math.min(expires, Math.floor((created + 86400000 - Date.now()) / 1000));
          if (expires <= 0) return;
        }
        const tombstone = "eduvia:ba:revoked:" + createHash("sha256").update(key).digest("hex");
        await (await redis()).eval("if redis.call('EXISTS',KEYS[2])==1 then return 0 end; redis.call('SET',KEYS[1],ARGV[1],'EX',ARGV[2]); return 1", { keys: ["eduvia:ba:" + key, tombstone], arguments: [encryptStorage(key, value), String(Math.max(1, expires))] });
      },
      async delete(key: string) {
        const connection = await redis();
        if (key.startsWith("active-sessions-") || key.startsWith("verification:")) { await connection.del("eduvia:ba:" + key); return; }
        await connection.eval("redis.call('SET',KEYS[2],'1','EX',86400); return redis.call('DEL',KEYS[1])", { keys: ["eduvia:ba:" + key, "eduvia:ba:revoked:" + createHash("sha256").update(key).digest("hex")], arguments: [] });
      },
    };
