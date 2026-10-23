# Eduvia backend

FastAPI/Python API and Celery worker for Eduvia: identity/workspaces, classes and invitations, jobs/usage/storage, knowledge and retrieval, authoring, AI drafts, exams/exports, assignments and assessment (`/v1`, see `contracts/openapi.json`). Authentication uses fixed-issuer RS256 access tokens; all tenant data is behind FORCE row-level security under a restricted runtime role. See [Auth0 setup](../deploy/auth0/README.md) before enabling real accounts and [DEVELOPMENT.md](../DEVELOPMENT.md#what-is-implemented) for what is verified and what is not.

## Local development

Use Python 3.12. From the repository root, `scripts/setup.ps1` installs dependencies into `backend/.venv` and `scripts/dev-backend.ps1` starts the API on `http://127.0.0.1:8000`. The Windows runner selects the event loop required by the async PostgreSQL driver. Restart this backend process after Python source edits.

On Linux/macOS, from this folder:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
cp .env.example .env
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log
```

The API can boot without PostgreSQL/Redis. `GET /health/live` returns process liveness, while `GET /health/ready` probes PostgreSQL and Redis concurrently and returns 503 when either is unavailable. Errors omit connection strings and credentials. Interactive API documentation is available at `/docs` in development only.

## Configuration

Settings are read from process environment variables and `.env`; process values take precedence. See [.env.example](.env.example). `APP_ENV` supports `development`, `test`, and `production`. CORS origins are a JSON list of exact origins. Keep secrets on the backend.

Run the bootstrap migration separately:

```sh
alembic upgrade head
```

Migrations enable pgvector and create `edu.users`, `edu.workspaces`, and `edu.workspace_members`, issuer-scoped identities and RLS. Migration 0004 is forward-only and requires an explicit mapping for existing user issuers; see the Auth0 setup guide. Run migrations as `eduvia_migrator`; API uses `eduvia_runtime`, never a superuser. No schema creation occurs during API startup.

## Worker

Run Celery in Linux, preferably with root Compose:

```sh
celery -A app.worker:celery_app worker --loglevel=INFO --concurrency=2 -Q default,ingestion,generation,export,omr
celery -A app.worker:celery_app beat --loglevel=INFO   # exactly one instance
```

`edu.background_jobs` is the source of truth; broker messages (JSON) carry only job IDs. `app.tasks.jobs.run` executes ingestion, embedding, generation, export and `attempt.grade` jobs under the job actor's RLS context with leases and idempotent stages. The beat task `app.tasks.jobs.sweep` (every 60 s) re-dispatches lost jobs, expires overdue attempts and applies `after_close` releases; without beat those never happen. Uploads need an S3-compatible bucket (`S3_*` settings); no bucket is created automatically.

## Checks and contract

```sh
python -m ruff check .
python -m ruff format --check .
python -m pytest -q -p no:cacheprovider          # unit + static gates; *_integration.py skip without a DB
python scripts/export_openapi.py ../contracts/openapi.json
```

Without `AUTH_TEST_DATABASE_URL` the run reports the PostgreSQL integration tests as skipped (37 at the time of writing); skipped is not passed. Static release gates run in every invocation and need no services:

```sh
python -m pytest -q tests/test_qa_gates.py          # key leak in OpenAPI, 401/404, FORCE RLS, no runtime DELETE, forward-only, single head
python -m pytest -q tests/test_privacy_inventory.py # tasks/decisions/0008 lists every table with person columns
python -m pytest -q tests/test_alert_checks.py      # deploy/alerts/check.py threshold logic
```

Tests replace infrastructure probes and do not require live services. `uv.lock` is the cross-platform resolution source; exported `requirements.lock` and `requirements-dev.lock` support pip/containers. Update dependencies deliberately with uv, regenerate both exports, and rerun the checks. See [DEVELOPMENT.md](../DEVELOPMENT.md) for the full workflow.

## Auth integration tests

`AUTH_TEST_DATABASE_URL` enables destructive setup **only on a disposable database ending in `_test`**. It recreates the `edu` schema, checks upgrade from 0003 with existing data, concurrent bootstrap, rollback and runtime-role isolation. It must never point to a development database containing work to preserve.

From the repo root, start `docker compose -f compose.auth-test.yaml up -d --wait`. Set `AUTH_TEST_DATABASE_URL` to the administrator test URL documented in `compose.auth-test.yaml`, then run `python -m pytest tests/test_identity_integration.py tests/test_auth.py -q` from this directory. To cover every migration (0005–0011) on PostgreSQL, run all integration suites against the same disposable database:

```sh
python -m pytest -q tests/test_bootstrap.py tests/test_auth.py tests/test_*_integration.py
```

CI currently runs only `test_bootstrap.py`, `test_identity_integration.py` and `test_auth.py` in its `auth-integration` job. Other tests do not need live infrastructure. Windows tests select the same Selector event loop as the API launcher; async tests require local socket permission outside restrictive sandboxes. A per-test timeout prevents silent hangs.

The new identity endpoints return `{error:{code,message},requestId}` and `Cache-Control: no-store`; health retains its existing contract. Tokens are never accepted through user/workspace identity headers. Public CORS still supports only the health browser request: authenticated browser calls go through the Next.js BFF.
