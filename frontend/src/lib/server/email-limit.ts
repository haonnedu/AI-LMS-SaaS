import "server-only";
import { createHash } from "node:crypto";
import { redis } from "./session-store";

export async function allowEmail(action: string, email: string) {
  const key = "eduvia:email-limit:" + createHash("sha256").update(action + ":" + email.trim().toLowerCase()).digest("hex");
  return await (await redis()).eval(`
    local now=tonumber(ARGV[1]); redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',now-3600000)
    local latest=redis.call('ZREVRANGE',KEYS[1],0,0,'WITHSCORES')
    if (#latest>0 and now-tonumber(latest[2])<60000) or redis.call('ZCARD',KEYS[1])>=5 then return 0 end
    redis.call('ZADD',KEYS[1],now,ARGV[1]); redis.call('EXPIRE',KEYS[1],3600); return 1`,
    { keys: [key], arguments: [String(Date.now())] }) === 1;
}
