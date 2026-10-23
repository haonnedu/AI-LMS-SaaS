import { createCipheriv, createDecipheriv, randomBytes, randomUUID } from "node:crypto";
import { createClient } from "redis";
import type { SessionData, SessionDataStore } from "@auth0/nextjs-auth0/types";

let client: ReturnType<typeof createClient> | undefined;
let connecting: Promise<unknown> | undefined;
export async function redis() {
  if (!client) {
    if (!process.env.SESSION_REDIS_URL) throw new Error("session_store_unconfigured");
    // Command timeout covers the send queue; socket timeout also bounds a sent command
    // whose server stops replying. Heartbeats keep healthy idle connections open.
    client = createClient({ url: process.env.SESSION_REDIS_URL, socket: { connectTimeout: 3000, socketTimeout: 3000, reconnectStrategy: false }, pingInterval: 1000, disableOfflineQueue: true, commandOptions: { timeout: 3000 } });
    client.on("error", () => { /* Request handlers emit bounded error codes only. */ });
  }
  if (!client.isReady) {
    if (!client.isOpen) connecting ??= client.connect().finally(() => { connecting = undefined; });
    if (connecting) await connecting;
    if (!client.isReady) throw new Error("session_store_unavailable");
  }
  return client;
}
function key() {
  const value = process.env.SESSION_ENCRYPTION_KEY;
  if (!value || !/^[a-f0-9]{64}$/i.test(value)) throw new Error("session_key_unconfigured");
  return Buffer.from(value, "hex");
}
function seal(id: string, session: SessionData) {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key(), iv);
  cipher.setAAD(Buffer.from(id));
  const body = Buffer.concat([cipher.update(JSON.stringify(session), "utf8"), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), body]).toString("base64");
}
function open(id: string, value: string): SessionData {
  const packed = Buffer.from(value, "base64");
  const cipher = createDecipheriv("aes-256-gcm", key(), packed.subarray(0, 12));
  cipher.setAAD(Buffer.from(id));
  cipher.setAuthTag(packed.subarray(12, 28));
  return JSON.parse(Buffer.concat([cipher.update(packed.subarray(28)), cipher.final()]).toString());
}
function ttl(session: SessionData) {
  return Math.max(0, Math.min(7200, session.internal.createdAt + 86400 - Math.floor(Date.now() / 1000)));
}
const prefix = "eduvia:session:";
export const sessionStore: SessionDataStore = {
  async get(id) {
    const value = await (await redis()).get(prefix + id);
    if (!value) return null;
    const session = open(id, value);
    return ttl(session) > 0 ? session : null;
  },
  async set(id, session) {
    const expires = ttl(session);
    if (expires > 0) await (await redis()).set(prefix + id, seal(id, session), { EX: expires });
  },
  async update(id, session) {
    const expires = ttl(session);
    if (expires <= 0) return false;
    // Atomic existence check prevents in-flight requests resurrecting a logged-out session.
    return (await (await redis()).set(prefix + id, seal(id, session), { EX: expires, XX: true })) === "OK";
  },
  async delete(id) { await (await redis()).del(prefix + id); },
};

export async function withSessionLock<T>(id: string, action: () => Promise<T>): Promise<T> {
  const connection = await redis();
  const name = "eduvia:lock:" + id;
  const owner = randomUUID();
  const deadline = Date.now() + 7000;
  while (await connection.set(name, owner, { NX: true, PX: 30000 }) !== "OK") {
    if (Date.now() >= deadline) throw new Error("session_busy");
    await new Promise(resolve => setTimeout(resolve, 40));
  }
  try { return await action(); }
  finally { await connection.eval("if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) end return 0", { keys: [name], arguments: [owner] }); }
}
