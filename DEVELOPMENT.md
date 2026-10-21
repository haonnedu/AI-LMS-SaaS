# Eduvia development guide

## What is implemented

This repository is a runnable foundation for the design in [ARCHITECTURE.md](ARCHITECTURE.md) and [DATABASE.md](DATABASE.md). It contains:

- A Next.js App Router/TypeScript frontend with 11 interactive preview pages and API connectivity feedback; educational records shown in the previews are sample data.
- A FastAPI application with environment configuration, request IDs, logging, health probes, and an OpenAPI contract.
- Async PostgreSQL sessions, Redis connectivity, Alembic migration setup, and a Celery worker entry point.
- Bootstrap migration for `edu`/pgvector and an identity migration for users, workspaces and workspace members. Runtime roles, tenant context and RLS are not implemented yet.
- Local Docker Compose, native Windows scripts, dependency lock files, and CI checks.

Authentication, workspace membership APIs/RLS, document upload, RAG, generation, enrollment, quiz submission, OMR, and billing are **planned**, not connected functionality. The UI previews do not create real accounts or persist educational records. A green API indicator means the API process is reachable; it does not imply database readiness or completed product workflows.

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

Windows PowerShell 5.1 and PowerShell 7 are supported. Setup validates Python 3.12 before installing anything. It uses a valid existing backend virtualenv, or discovers Python 3.12 via the Python launcher/PATH. To select an interpreter explicitly and validate without writing files or installing packages:

```powershell
.\scripts\setup.ps1 -Python312 'C:\path\to\Python312\python.exe' -CheckOnly
```

Remove `-CheckOnly` to install. An invalid existing virtualenv is reported and left intact; deliberately move it aside before recreating it if needed. `-SkipInstall` only creates missing environment files, without validating/installing Python. `-CheckOnly` takes precedence if both switches are passed.

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

## Planned implementation and service expansion

[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) is the detailed delivery backlog: M0 baseline, M1 identity/RLS, M2 jobs/quotas/storage, M3 knowledge, M4 authoring/blueprints, M5 classes, M6 assessment, M7 pilot. Add versioned single-choice exam blueprints and question-to-objective metadata in authoring; see [EXAM_BLUEPRINTS.md](EXAM_BLUEPRINTS.md).

Independent self-study is a later L0–L4 track described in [STUDENT_LEARNING.md](STUDENT_LEARNING.md), distinct from the classroom student portal. Its proposed student-learning service owns goals/plans/mastery, while core retains content/blueprint publication and authoritative assessment/scoring. The current class-assignment schema requires a standalone learner assessment extension before this integration.

No student-learning source directory, database, API, worker, event broker or Compose service is provisioned by these planning documents. Do not run undocumented service commands or assume the current OpenAPI exposes these APIs. A module-first implementation may precede extraction; when separated, use independent migrations/credentials, scoped APIs and durable outbox/inbox events, never direct cross-service table access. Baseline CI will need learner-isolation, API-contract, replay/revocation/deletion and service-failure tests before that release.

This documentation update does not revalidate earlier foundation test results. Re-run the baseline in M0 and record actual outcomes. Keep design targets separate from the implemented checklist at the top of this guide.

## Troubleshooting

- **API is offline:** start the backend and check `API_INTERNAL_URL` in `frontend/.env.local`; restart Next.js after changing it.
- **Readiness is unavailable:** start PostgreSQL/Redis and check backend URLs. An available API process can still report dependency failure.
- **Port already in use:** stop the other local process or change the relevant environment values consistently.
- **Migration cannot enable pgvector:** use the provided pgvector image or install the extension in your PostgreSQL server; a Python package alone cannot supply the server extension.
- **Dependency installation fails:** verify Python/Node versions and network access to PyPI/npm; avoid substituting unreviewed dependency versions.
- **Compose fails after changing a database password:** existing volume credentials do not change automatically. Update the database credential deliberately; do not delete the volume to repair a password mismatch if it contains needed data.

Compose startup ordering follows the [Docker Compose dependency guidance](https://docs.docker.com/compose/how-tos/startup-order/). Database installation details are in the [pgvector project](https://github.com/pgvector/pgvector#installation).

## Tooling regression and disposable integration checks

From the repository root, using the backend Python 3.12 virtualenv:

```powershell
.\backend\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml scripts
.\backend\.venv\Scripts\python.exe -m ruff format --check --config backend/pyproject.toml scripts
.\backend\.venv\Scripts\python.exe -m pytest -c backend/pyproject.toml scripts/tests -q
.\backend\.venv\Scripts\python.exe scripts/verify-m0.py
```

On Linux use `backend/.venv/bin/python` instead. Unit tests do not call Docker; setup tests run both Windows shells and are skipped on Linux. CI installs the locked backend development dependencies for these checks.

The verifier needs Docker with Compose and access to build dependencies. It builds current source, creates a unique project with free loopback ports and its own temporary DB volume, and ignores the repository `.env` and inherited Compose overrides. It checks bootstrap, the single Alembic head, the current three identity tables, repeated upgrades, downgrade/upgrade, all 11 pages, health/proxy, and loss/recovery of PostgreSQL, Redis and API. Update its explicit table expectations when future migrations intentionally change the schema. This does not test RLS or product workflows.

Evidence is written under `tmp/eduvia-m0-<UTC timestamp>-<random>/`: `result.json` includes expected head, observed tables, source commit, dirty-tree summary, ports and failed step; `commands.log` includes command exit codes and redacted diagnostics. Build commands time out after 900 seconds, other Compose commands after 180 seconds. Cleanup is attempted on failures as well; a cleanup error fails the run and identifies the specific project to inspect. Never run broad volume deletion to recover from a failed verification.

The disposable environment file is removed at the end. Do not share it while a run is active. CI uploads only `result.json` and `commands.log`; the Ubuntu containers job runs this verifier, while a Windows/Linux scripts job runs lint/format/regression checks. GitHub CI results apply only to the commit being tested. See [tooling handoff](discuss/BASE-tooling-ci.md) for recorded results and limitations.

## Historical scaffold validation

The original scaffold was checked with Node 24/Python 3.12, including 16 backend tests and four initial page routes. That record predates the identity migration, expanded preview UI and Docker-backed verification. It is historical context, not evidence for the current revision; use the linked handoffs and current CI runs for acceptance.
