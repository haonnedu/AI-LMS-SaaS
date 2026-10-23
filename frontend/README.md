# Eduvia frontend

Next.js App Router + React + TypeScript + Tailwind CSS. The app includes public teaching previews and a separate authenticated account flow: Better Auth email/password and Google login, email verification, personal workspace bootstrap and a real `/dashboard`. Preview educational records remain sample data; accounts require the [Better Auth setup](../deploy/better-auth/SETUP-LOCAL.md).

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
| `/login` | Eduvia email/password form and Google login |
| `/verify-email` | Email verification instructions and rate-limited resend |
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

1. Configure Google OAuth/email and complete the real-provider smoke described in the setup guide.
2. Obtain independent review and second-machine evidence for the implemented identity/workspace slice.
3. Add source ingestion and teacher-reviewed drafts before student publication.
4. Implement enrollment and the online quiz flow before OMR.

Do not place tenant records or answer keys in static page data. Authenticated fetches must opt out of shared caches. Do not add mutation controls until the corresponding authorized backend workflow exists. Keep personal and school workspaces separate, and implement explicit copy semantics before enabling cross-workspace reuse.

## Authentication and test boundaries

The production entrypoints no longer mount the mock auth/workspace providers. Old mock adapters remain as historical preview fixtures/tests; they do not grant access to `/dashboard` or backend data. Session/token data is encrypted in Redis and a host-only HttpOnly cookie identifies the session. Refresh, logout and session updates use the same per-session distributed lock. No SDK access-token endpoint is exposed to the browser. All BFF mutations check Origin and a session CSRF token.

`npm run test:better-auth` (alias `test:auth`) runs Playwright against actual Next.js/FastAPI, disposable PostgreSQL/Redis, SMTP and signed Google fixtures. Ports: frontend 3106, API 8006, fixture control 9112, SMTP 1026, PostgreSQL 5434, Redis 6381. Set AUTH_TEST_PYTHON if needed. Setup resets only the database ending in `_test`; do not run alongside backend integration tests.

Install Chromium with `npx playwright install chromium`. Generated diagnostics are ignored; never upload real-user session traces. Real Google/email and HTTPS staging smoke remain separate gates. Account linking is explicit and same-email; `/account` manages methods. No Auth0 SDK, provider switch or identity-transfer endpoint remains. See [runbook](../deploy/better-auth/README.md).

## Native local email smoke

Start `docker compose --profile dev-mail up -d --wait db redis mailpit` from root, then run native backend/frontend per [setup](../deploy/better-auth/SETUP-LOCAL.md). Mailpit UI is http://127.0.0.1:8025, SMTP loopback 1025; messages are not delivered externally. `npm run test:auth:local` exercises the existing native app and Mailpit without schema reset, creates a synthetic local account/workspace each run and requires Chromium. This is separate from disposable CI fixtures; real Google setup remains manual.
