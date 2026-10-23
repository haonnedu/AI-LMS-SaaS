# Eduvia backend

FastAPI/Python API for Eduvia. Health endpoints and `/v1` identity/workspace endpoints are implemented. Authentication uses fixed-issuer RS256 access tokens; user and workspace bootstrap runs atomically under a restricted runtime role. See [Better Auth setup](../deploy/better-auth/README.md) before enabling real accounts. Product teaching/AI/grading modules remain planned.

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

Migrations enable pgvector and create `edu.users`, `edu.workspaces`, and `edu.workspace_members`, issuer-scoped identities and RLS. Migration 0004 is forward-only and requires an explicit mapping for existing user issuers; see the historical migration notes. Run migrations as `eduvia_migrator`; API uses `eduvia_runtime`, never a superuser. No schema creation occurs during API startup.

## Worker

Run Celery in Linux, preferably with root Compose:

```sh
celery -A app.worker:celery_app worker --loglevel=INFO --concurrency=2 -Q default,ingestion,generation,export,omr
```

The registered `app.tasks.health.ping` task is a connectivity check, not an AI or grading pipeline. Broker messages use JSON. Implement PostgreSQL job/outbox records, idempotent stages, and lease recovery before adding durable business jobs.

Object storage has a configuration/factory boundary only; no S3 calls occur at startup, and no upload API or bucket is created.

## Checks and contract

```sh
python -m ruff check .
python -m pytest
python scripts/export_openapi.py ../contracts/openapi.json
```

Tests replace infrastructure probes and do not require live services. `uv.lock` is the cross-platform resolution source; exported `requirements.lock` and `requirements-dev.lock` support pip/containers. Update dependencies deliberately with uv, regenerate both exports, and rerun the checks. See [DEVELOPMENT.md](../DEVELOPMENT.md) for the full workflow.

## Auth integration tests

`AUTH_TEST_DATABASE_URL` enables destructive setup **only on a disposable database ending in `_test`**. It recreates the `edu` schema, checks upgrade from 0003 with existing data, concurrent bootstrap, rollback and runtime-role isolation. It must never point to a development database containing work to preserve.

From the repo root, start `docker compose -f compose.auth-test.yaml up -d --wait`. Set `AUTH_TEST_DATABASE_URL` to the administrator test URL documented in `compose.auth-test.yaml`, then run `python -m pytest tests/test_identity_integration.py tests/test_auth.py -q` from this directory. Other tests do not need live infrastructure. Windows tests select the same Selector event loop as the API launcher; async tests require local socket permission outside restrictive sandboxes. A per-test timeout prevents silent hangs.

The new identity endpoints return `{error:{code,message},requestId}` and `Cache-Control: no-store`; health retains its existing contract. Tokens are never accepted through user/workspace identity headers. Public CORS still supports only the health browser request: authenticated browser calls go through the Next.js BFF.

## Multiple identities and Better Auth

Migration history 0001–0007 is retained; 0008 retires the transfer function/table and refuses unreviewed nonempty transfer receipts. Runtime accepts only the configured Better Auth issuer; `/v1/auth/migrate` is removed. `user_identities` remains the provisioning/RLS mapping. Auth storage uses `eduvia_auth_runtime`; API keeps `eduvia_runtime`. Operator-only dry-run cleanup is documented in the [runbook](../deploy/better-auth/README.md).
