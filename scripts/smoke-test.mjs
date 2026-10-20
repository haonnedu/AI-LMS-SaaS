// Run against already-started processes. No writes or seeded data.
const frontend = process.env.FRONTEND_URL ?? 'http://127.0.0.1:3000';
const api = process.env.API_URL ?? 'http://127.0.0.1:8000';

async function get(base, path) {
  const response = await fetch(new URL(path, base), { signal: AbortSignal.timeout(15_000) });
  if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
  return response;
}

for (const path of ['/', '/library', '/classes', '/settings']) {
  const html = await (await get(frontend, path)).text();
  if (!html.includes('Eduvia')) throw new Error(`${path} did not render the Eduvia shell`);
  console.log(`PASS frontend ${path}`);
}
for (const [base, path] of [[api, '/health/live'], [frontend, '/api/backend/health']]) {
  const body = await (await get(base, path)).json();
  if (body.status !== 'ok' || body.service !== 'eduvia-api') {
    throw new Error(`${path} returned an unexpected API contract`);
  }
  console.log(`PASS API contract ${path}`);
}
if (process.env.CHECK_READINESS === '1') {
  await get(api, '/health/ready');
  console.log('PASS API readiness');
}
