import { randomUUID } from "node:crypto";
import { createClient } from "redis";

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
