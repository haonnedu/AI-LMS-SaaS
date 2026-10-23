import { createClient } from "redis";

// Suites share one fixture IP. Reset only its rate counters between independent
// scenarios; production limits remain enabled and are tested separately.
export async function resetRates() {
  const connection = createClient({ url: "redis://127.0.0.1:6381/3" });
  await connection.connect();
  try {
    const keys = await connection.keys("eduvia:ba:counter:*");
    if (keys.length) await connection.del(keys);
  } finally { await connection.close(); }
}
