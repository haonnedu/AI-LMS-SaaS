import { spawn, spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { generateKeyPairSync, randomUUID, createHash, sign } from 'node:crypto';
import { createServer } from 'node:http';
import { createServer as smtpServer } from 'node:net';

const root = resolve('..'), service = process.argv[2];
const python = process.env.AUTH_TEST_PYTHON || resolve(root, 'backend', process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
const env = { ...process.env, PYTHONPATH: resolve(root, 'backend'), APP_ENV: 'test', AUTH_TEST_MODE: '1',
  AUTH_TEST_DATABASE_URL: 'postgresql+psycopg://postgres:auth_test_only@127.0.0.1:5434/eduvia_auth_test',
  DATABASE_URL: 'postgresql+psycopg://eduvia_runtime:runtime_test_only@127.0.0.1:5434/eduvia_auth_test', AUTH_DATABASE_URL: 'postgresql://eduvia_auth_runtime:auth_runtime_test_only@127.0.0.1:5434/eduvia_auth_test',
  AUTH_ISSUER: 'http://127.0.0.1:3106', AUTH_AUDIENCE: 'https://eduvia-api', AUTH_JWKS_URL: 'http://127.0.0.1:3106/api/auth/jwks',
  APP_BASE_URL: 'http://127.0.0.1:3106', API_INTERNAL_URL: 'http://127.0.0.1:8006', BETTER_AUTH_SECRET: 'better-auth-test-secret-'.repeat(3), BETTER_AUTH_AUDIENCE: 'https://eduvia-api',
  SESSION_ENCRYPTION_KEY: 'c'.repeat(64), SESSION_REDIS_URL: 'redis://127.0.0.1:6381/3', REDIS_URL: 'redis://127.0.0.1:6381/0', SMTP_URL: 'smtp://127.0.0.1:1026', AUTH_EMAIL_FROM: 'Eduvia <auth@example.test>', GOOGLE_CLIENT_ID: 'fixture-google', GOOGLE_CLIENT_SECRET: 'fixture-google-secret' };
if (service === 'mail') {
  const result = spawnSync(python, [resolve(root, 'frontend/tests/better-auth/setup.py')], { cwd: resolve(root, 'backend'), env, stdio: 'inherit' });
  if (result.status !== 0) process.exit(1);
  const messages = [], codes = new Map();
  let identity = { sub: 'google-fixture', email: 'google@example.test', email_verified: true };
  const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
  const jwk = { ...publicKey.export({ format: 'jwk' }), kid: 'google-test-key', alg: 'RS256', use: 'sig' };
  function token(payload) { const head = Buffer.from(JSON.stringify({ alg: 'RS256', kid: jwk.kid })).toString('base64url'), body = Buffer.from(JSON.stringify(payload)).toString('base64url'); const message = head + '.' + body; return message + '.' + sign('RSA-SHA256', Buffer.from(message), privateKey).toString('base64url'); }
  smtpServer(socket => {
    socket.write('220 test SMTP\r\n'); let buffer = '', data = false, content = '';
    socket.on('data', chunk => {
      buffer += chunk.toString();
      while (buffer.includes('\r\n')) {
        const index = buffer.indexOf('\r\n'), line = buffer.slice(0, index); buffer = buffer.slice(index + 2);
        if (data) { if (line === '.') { messages.push(content); content = ''; data = false; socket.write('250 accepted\r\n'); } else content += line + '\n'; }
        else if (/^EHLO/i.test(line)) socket.write('250-test\r\n250 OK\r\n');
        else if (/^DATA/i.test(line)) { data = true; socket.write('354 send\r\n'); }
        else if (/^QUIT/i.test(line)) socket.end('221 bye\r\n');
        else socket.write('250 OK\r\n');
      }
    });
  }).listen(1026, '127.0.0.1');
  createServer(async (request, response) => {
    const url = new URL(request.url, 'http://127.0.0.1:9112');
    response.setHeader('Content-Type', 'application/json');
    if (url.pathname === '/identity') {
      let body = ''; for await (const chunk of request) body += chunk;
      identity = JSON.parse(body); response.end('{}');
    } else if (url.pathname === '/certs') response.end(JSON.stringify({ keys: [jwk] }));
    else if (url.pathname === '/authorize') {
      const code = randomUUID(); codes.set(code, { ...identity, challenge: url.searchParams.get('code_challenge') });
      const callback = new URL(url.searchParams.get('redirect_uri')); callback.searchParams.set('state', url.searchParams.get('state')); callback.searchParams.set('code', code);
      response.writeHead(302, { Location: callback.href }); response.end();
    } else if (url.pathname === '/token') {
      let body = ''; for await (const chunk of request) body += chunk;
      const params = new URLSearchParams(body), code = params.get('code'), account = codes.get(code); codes.delete(code);
      if (!account || account.challenge !== createHash('sha256').update(params.get('code_verifier') || '').digest('base64url')) { response.writeHead(400); response.end('{"error":"invalid_grant"}'); return; }
      const now = Math.floor(Date.now() / 1000);
      response.end(JSON.stringify({ access_token: 'fixture-only', token_type: 'Bearer', expires_in: 300, id_token: token({ iss: 'https://accounts.google.com', aud: 'fixture-google', iat: now, exp: now + 300, sub: account.sub, email: account.email, email_verified: account.email_verified, name: 'Google Teacher' }) }));
    } else response.end(JSON.stringify(messages));
  }).listen(9112, '127.0.0.1');
} else {
  const command = service === 'api' ? python : process.execPath;
  const args = service === 'api' ? ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8006', '--no-access-log', '--loop', 'asyncio'] : ['node_modules/next/dist/bin/next', 'dev', '--webpack', '--hostname', '127.0.0.1', '--port', '3106'];
  // On Windows use the project's selector-loop entrypoint.
  if (service === 'api' && process.platform === 'win32') args.splice(0, args.length, resolve(root, 'frontend/tests/better-auth/api.py'));
  if (service === 'frontend') env.NODE_OPTIONS = (env.NODE_OPTIONS || '') + ' --import=' + pathToFileURL(resolve(root, 'frontend/tests/better-auth/google-fetch.mjs')).href;
  const child = spawn(command, args, { cwd: resolve(root, service === 'api' ? 'backend' : 'frontend'), env, stdio: 'inherit' });
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
  child.on('exit', code => process.exit(code || 0));
}
