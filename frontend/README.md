# Eduvia frontend

Next.js App Router + React + TypeScript + Tailwind CSS. The app includes public teaching previews and a separate authenticated account flow: Auth0-hosted signup/login, email verification, personal workspace bootstrap and a real `/dashboard`. Preview educational records remain sample data; accounts require the [Auth0 setup](../deploy/auth0/README.md).

## Run locally

Use Node.js 24 LTS. From this directory:

```powershell
npm.cmd ci
Copy-Item .env.example .env.local
npm.cmd run dev
```

Open http://127.0.0.1:3000. Start the FastAPI backend on port 8000 to see the connection become available. On macOS/Linux, use `npm` and `cp .env.example .env.local` instead. `npm.cmd` avoids Windows PowerShell script execution-policy issues.

## Pages

| Route | Included behavior |
| --- | --- |
| `/` | Workspace overview, navigation, workflow introduction, live connection status |
| `/library` | Honest library empty state and intended ownership model |
| `/classes` | Classroom empty state and pilot roadmap |
| `/settings` | Foundation state, connection check with retry, implementation milestones |
| `/login` | Hosted Auth0 login and signup entry points |
| `/verify-email` | Signed-in account verification and resend controls |
| `/onboarding` | Protected personal workspace bootstrap/retry |
| `/dashboard` | Protected current user and membership-scoped workspace selector |
| `/api/backend/health` | Server-only fixed-upstream liveness proxy |

## API boundary

`API_INTERNAL_URL` is server-only and defaults to `http://127.0.0.1:8000`. Compose uses `http://api:8000`. The proxy always calls `/health/live`, ignores request query/body input, disallows redirects, uses a four-second timeout, validates the response, and only returns allowlisted fields. It never exposes backend exception text or configuration. The browser uses the same-origin proxy and never receives service credentials.

Success: `{ "status": "ok", "service": "eduvia-api", "version": "0.1.0" }`. A failed or malformed response returns HTTP 503 with a generic `backend_unavailable` error. Liveness does not prove database readiness, authorization, or a working background queue. The check is manual on mount/retry and does not persist health status.

Generate the reviewed API contract types after backend changes:

```powershell
npm.cmd run api:generate
```

The source is `../contracts/openapi.json`; output is `src/lib/api/generated.ts`. Runtime validation remains necessary because generated types cannot validate network responses.

## Quality checks

```powershell
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
npm.cmd run start
```

Lint is a separate required check. Direct packages and the full dependency graph are pinned in `package.json` and `package-lock.json`. TypeScript 5.9.3 matches the OpenAPI generator's peer dependency range; check generator and lint compatibility before upgrading its major version. There are no remote font or image dependencies.

## Source layout

```text
src/app/                  Pages, root layout, styles, and the health proxy
src/components/           Workspace shell and reusable presentational components
src/lib/api/              Runtime health validation and generated contract types
public/                   Local brand assets
```

The build uses Webpack for consistent native Windows behavior. Its postbuild step prepares standalone assets; `npm run start` launches that bundle and loads `.env.local`. Local commands bind to loopback; the container entrypoint binds to `0.0.0.0` inside its container. Follow root deployment instructions before exposing the development foundation publicly.

## Next implementation milestones

1. Configure Auth0/email and complete the real-provider smoke described in the setup guide.
2. Obtain independent review and second-machine evidence for the implemented identity/workspace slice.
3. Add source ingestion and teacher-reviewed drafts before student publication.
4. Implement enrollment and the online quiz flow before OMR.

Do not place tenant records or answer keys in static page data. Authenticated fetches must opt out of shared caches. Do not add mutation controls until the corresponding authorized backend workflow exists. Keep personal and school workspaces separate, and implement explicit copy semantics before enabling cross-workspace reuse.

## Authentication and test boundaries

The production entrypoints no longer mount the mock auth/workspace providers. Old mock adapters remain as historical preview fixtures/tests; they do not grant access to `/dashboard` or backend data. Session/token data is encrypted in Redis and a host-only HttpOnly cookie identifies the session. Refresh, logout and session updates use the same per-session distributed lock. No SDK access-token endpoint is exposed to the browser. All BFF mutations check Origin and a session CSRF token.

`npm run test:auth` runs Playwright with a loopback OIDC fixture, the actual FastAPI backend and Redis. First initialize the disposable PostgreSQL schema with backend identity integration tests. Default ports are frontend 3105, API 8005, OIDC 9101, PostgreSQL 5434 and Redis 6381. Set `AUTH_TEST_PYTHON` if the backend virtualenv is elsewhere; CI uses `python`. The fixture is a test executable outside application code and cannot enable mock auth in production. Its private signing key is generated at startup.

Use `npx playwright install chromium` once. Tests write `.next-auth-test`, `test-results` and fixture-only captures under `evidence/auth`; do not upload traces from real-user sessions. `AUTH_TEST_MODE` is for the fixture runner only. Tests cover hosted auth redirects, provisioning, persistence, logout/cookie replay, unverified email, verification quotas, refresh serialization, Redis timeout/recovery and session lifetime. Actual verification/reset emails require manual smoke with Auth0 and a real mailbox.
