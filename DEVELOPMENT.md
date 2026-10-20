# Eduvia development guide

## What is implemented

This repository is a runnable foundation for the design in [ARCHITECTURE.md](ARCHITECTURE.md) and [DATABASE.md](DATABASE.md). It contains:

- A Next.js App Router/TypeScript frontend with responsive workspace navigation, empty library/classroom states, and API connectivity feedback.
- A FastAPI application with environment configuration, request IDs, logging, health probes, and an OpenAPI contract.
- Async PostgreSQL sessions, Redis connectivity, Alembic migration setup, and a Celery worker entry point.
- A bootstrap migration for the `edu` schema and pgvector; no educational or tenant data tables yet.
- Local Docker Compose, native Windows scripts, dependency lock files, and CI checks.

Authentication, workspace membership/RLS, document upload, RAG, generation, enrollment, quiz submission, OMR, and billing are **planned**, not connected functionality. The UI has no fake user accounts or stored educational records. A green API indicator means the API process is reachable; it does not imply database readiness or completed product workflows.

## Repository layout

```text
frontend/             Next.js application, UI components, typed API contract
backend/              FastAPI, configuration, database, migrations, Celery, tests
contracts/            OpenAPI snapshot exported from the backend
scripts/              Windows setup/run commands and HTTP smoke checks
compose.yaml          Local infrastructure and application containers
.github/workflows/    Automated checks
ARCHITECTURE.md       Target application architecture
DATABASE.md           Target database design, not an executable full migration
```

## Prerequisites

- Node.js 24 LTS and npm. The frontend also declares its supported Node range.
- Python 3.12 for the backend.
- Docker Desktop with Compose v2 if running PostgreSQL, Redis, the worker, or the full container stack locally.

Keep Node/Python dependencies inside `frontend/node_modules` and `backend/.venv`. Never commit `.env` files. Copies of `.env.example` contain local-only defaults, not production credentials.

## Quick start on Windows

Open PowerShell in the repository folder:

```powershell
.\scripts\setup.ps1
```

This copies missing environment files without overwriting existing settings, creates a backend virtual environment, and installs locked frontend/backend dependencies. If PowerShell blocks local scripts, run them with a process-scoped policy:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

Start the backend in one terminal:

```powershell
.\scripts\dev-backend.ps1
```

Start the frontend in another terminal:

```powershell
.\scripts\dev-frontend.ps1
```

Open [Eduvia](http://localhost:3000), [API documentation](http://127.0.0.1:8000/docs), and [API liveness](http://127.0.0.1:8000/health/live).

Both processes can start without PostgreSQL or Redis. `/health/live` should succeed; `/health/ready` returns 503 until dependencies are available. This lets you develop the shell and API contract before starting infrastructure. The Windows backend runner selects a compatible asyncio event loop for the PostgreSQL driver.

For database/Redis-backed development, start infrastructure and migrate:

```powershell
docker compose up -d db redis
docker compose run --rm migrate
```

The native backend's default database and Redis settings match these services. To run the worker in Linux containers:

```powershell
docker compose up -d worker
```

Do not run a native Windows Celery worker as the reference development configuration; use the supplied container.

## Run everything in Docker

```powershell
.\scripts\setup.ps1 -SkipInstall
docker compose up --build
```

Compose starts PostgreSQL and Redis, runs the bootstrap migration once, then starts the API, worker, and frontend. The frontend container uses `http://api:8000` internally; browsers use the Next.js `/api/backend/health` endpoint rather than Docker hostnames. Native and container processes share host ports, so stop the native processes before running the full stack.

Container builds use production-style application bundles without source bind mounts. Rebuild after changes. Native Next.js provides hot reload; restart the native Windows backend after Python changes. Published service ports bind to `127.0.0.1` for local development. PostgreSQL data persists in the `postgres-data` volume; ordinary `docker compose down` preserves it.

| Service | Default local address |
|---|---|
| Frontend | `http://localhost:3000` |
| API | `http://127.0.0.1:8000` |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

Root `.env` controls Compose ports/database settings. `backend/.env` configures native Python processes. `frontend/.env.local` configures native Next.js. Changing a Compose port does not automatically rewrite the native process settings. URL-encode reserved characters in passwords embedded in a database connection URL.

## API contracts

The backend exports its schema without connecting to external services. From the repository root:

```powershell
.\backend\.venv\Scripts\python.exe .\backend\scripts\export_openapi.py .\contracts\openapi.json
```

Then regenerate the frontend types:

```powershell
cd frontend
npm.cmd run api:generate
```

Commit both `contracts/openapi.json` and `frontend/src/lib/api/generated.ts` when changing a public API. CI checks that regeneration has no unexplained diff. Type generation describes request/response shapes; runtime parsing and backend authorization remain necessary.

## Verification

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

From `frontend/`:

```powershell
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
```

With frontend and API running, from the repository root:

```powershell
node scripts/smoke-test.mjs
```

The smoke check verifies the four pages, direct API liveness, and the Next.js proxy response. To include database/Redis readiness:

```powershell
$env:CHECK_READINESS = '1'
node scripts/smoke-test.mjs
Remove-Item Env:CHECK_READINESS
```

Frontend/API URLs can be overridden with `FRONTEND_URL` and `API_URL` for this smoke check. Backend unit tests substitute dependency probes, so they do not prove that real PostgreSQL/Redis or a container deployment is working. Use the Compose/CI readiness check for that integration.

## Database and security boundaries

The migration does not implement the full schema illustrated in `DATABASE.md`. It creates the extension/schema foundation; the API never creates tables during startup. Inspect migrations before applying them and run `alembic upgrade head` as a separate deployment step.

The local PostgreSQL account is intentionally an owner account for bootstrapping an empty development database. Before adding tenant routes, provision separate migration/runtime roles, implement verified identity and workspace membership, apply RLS with composite tenant foreign keys, and test access isolation. Do not connect real student records to this scaffold until those controls exist.

The health proxy has a fixed server-configured upstream and does not accept a client-provided URL. Provider/database credentials must stay in backend environment variables; do not add them to `NEXT_PUBLIC_*` values. Production deployment, identity-provider configuration, TLS, secret management, and recovery are separate work from this local foundation.

## Next implementation slices

1. Identity provider integration, secure sessions, personal workspace creation, membership rules, and RLS tests.
2. Durable jobs/outbox, usage reservations, storage quotas, and rights-aware uploads.
3. Licensed/private document ingestion and source-aware generation with teacher review.
4. Class enrollment and immutable single-choice assessments with deterministic grading.

Implement one complete, tested workflow at a time. S3-compatible object-storage settings are an extension point; no bucket or upload endpoint is provisioned here. The Celery health task validates worker connectivity only; generation/OMR pipelines require the durable job design before implementation.

## Troubleshooting

- **API is offline:** start the backend and check `API_INTERNAL_URL` in `frontend/.env.local`; restart Next.js after changing it.
- **Readiness is unavailable:** start PostgreSQL/Redis and check backend URLs. An available API process can still report dependency failure.
- **Port already in use:** stop the other local process or change the relevant environment values consistently.
- **Migration cannot enable pgvector:** use the provided pgvector image or install the extension in your PostgreSQL server; a Python package alone cannot supply the server extension.
- **Dependency installation fails:** verify Python/Node versions and network access to PyPI/npm; avoid substituting unreviewed dependency versions.
- **Compose fails after changing a database password:** existing volume credentials do not change automatically. Update the database credential deliberately; do not delete the volume to repair a password mismatch if it contains needed data.

Compose startup ordering follows the [Docker Compose dependency guidance](https://docs.docker.com/compose/how-tos/startup-order/). Database installation details are in the [pgvector project](https://github.com/pgvector/pgvector#installation).

## Validation of this foundation

Checked on Windows with Node 24 and Python 3.12: 16 backend tests, Ruff lint/format, frontend lint/type checking/production build, standalone startup, all four page routes, frontend/API liveness integration, API-down/retry behavior in the browser, and bounded dependency-down readiness. PowerShell setup and Compose/CI YAML were checked. Docker is not installed on the authoring machine, so container builds, real database migration execution, and PostgreSQL/Redis-backed readiness remain to be verified in Docker/CI. The migration was checked in offline SQL generation mode.
