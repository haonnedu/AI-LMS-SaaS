# Eduvia backend

FastAPI/Python foundation for Eduvia. The current public surface is limited to liveness and readiness. Product modules are planned in [app/modules/README.md](app/modules/README.md); no fake authentication or tenant routes are enabled.

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

The migration enables pgvector and creates the `edu` namespace. It does not create the proposed domain schema or tenant/RLS policies. Migration credentials and restricted runtime credentials must be separated before tenant tables are added. No schema creation occurs during API startup.

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
