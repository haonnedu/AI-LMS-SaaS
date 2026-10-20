# Eduvia frontend

Next.js App Router + React + TypeScript + Tailwind CSS. The base source provides a responsive, accessible teacher workspace and a real API liveness connection. Product workflows are explicitly marked as upcoming; there are no simulated accounts, generated lessons, saved classes, or grades.

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

1. Integrate a reviewed identity provider and server-validated workspace context.
2. Add authorized workspace APIs and typed clients; never treat navigation or a selected workspace as authorization.
3. Add source ingestion and teacher-reviewed drafts before student publication.
4. Implement enrollment and the online quiz flow before OMR.

Do not place tenant records or answer keys in static page data. Authenticated fetches must opt out of shared caches. Do not add mutation controls until the corresponding authorized backend workflow exists. Keep personal and school workspaces separate, and implement explicit copy semantics before enabling cross-workspace reuse.
