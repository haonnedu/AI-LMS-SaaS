// Test-process preload only. Production code never rewrites Google endpoints.
if (process.env.AUTH_TEST_MODE !== '1' || process.env.NODE_ENV === 'production') throw Error('Test process required');
const originalFetch = globalThis.fetch;
globalThis.fetch = (input, init) => {
  const url = String(input instanceof Request ? input.url : input);
  const path = url === 'https://oauth2.googleapis.com/token' ? '/token' : url === 'https://www.googleapis.com/oauth2/v3/certs' ? '/certs' : null;
  return originalFetch(path ? 'http://127.0.0.1:9112' + path : input, init);
};
