"""Real PostgreSQL RLS checks for jobs, documents and quotas (disposable *_test database)."""

import asyncio
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote
from uuid import UUID, uuid4

import jwt
import pytest
from agreements_helper import accept_agreements, mount_agreements
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api import documents as documents_api
from app.api import jobs as jobs_api
from app.api.identity import ApiError
from app.api.workspace_access import workspace_transaction
from app.core.auth import CLAIM_NAMESPACE
from app.core.config import Settings, get_settings
from app.main import create_app
from app.services import usage

ADMIN_URL = os.getenv("AUTH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="Set AUTH_TEST_DATABASE_URL to disposable PostgreSQL"
)
ISSUER = "https://identity.example/"
PDF = b"%PDF-1.7\n" + b"0" * 64


@pytest.fixture(scope="module")
def database():
    assert ADMIN_URL and ADMIN_URL.rsplit("/", 1)[-1].endswith("_test"), "Test database required"
    engine = create_engine(ADMIN_URL)
    with engine.begin() as db:
        db.execute(text("DROP SCHEMA IF EXISTS edu CASCADE"))
        db.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
        db.execute(
            text("""DO $$ BEGIN
        IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='eduvia_runtime') THEN
          CREATE ROLE eduvia_runtime LOGIN PASSWORD 'runtime_test_only'
            NOSUPERUSER NOCREATEROLE NOBYPASSRLS;
        END IF;
        END $$;""")
        )
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = ADMIN_URL
    get_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
        get_settings.cache_clear()
    with engine.begin() as db:
        db.execute(text("GRANT USAGE ON SCHEMA edu TO eduvia_runtime"))
        name = engine.dialect.identifier_preparer.quote(engine.url.database)
        db.execute(text(f"GRANT CONNECT ON DATABASE {name} TO eduvia_runtime"))
    yield engine
    engine.dispose()


def runtime_url():
    return make_url(ADMIN_URL).set(username="eduvia_runtime", password="runtime_test_only")


class MemoryStore:
    """In-memory stand-in for the private bucket (S3 itself is covered by Stubber tests)."""

    def __init__(self):
        self.objects = {}

    async def aput(self, key, body, *, mime, size, sha256):
        self.objects[key] = body.read()

    async def adelete(self, key):
        self.objects.pop(key, None)

    def head(self, key):
        return {"ContentLength": len(self.objects[key])} if key in self.objects else None

    def delete(self, key):
        self.objects.pop(key, None)

    def presign_get(self, key, *, file_name, mime, ttl_seconds=60):
        raise AssertionError("not used")


@pytest.fixture
async def api(database):
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=runtime_url().render_as_string(hide_password=False),
        auth_issuer=ISSUER,
        auth_audience="eduvia-api",
        auth_jwks_url="https://identity.example/jwks",
        db_pool_size=3,
        db_max_overflow=2,
    )
    app = create_app(settings)
    mount_agreements(app)
    paths = {getattr(route, "path", "") for route in app.routes}
    for router in (documents_api.router, jobs_api.router):
        if not any(route.path in paths for route in router.routes):
            app.include_router(router)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.token_verifier.jwks.get_signing_key_from_jwt = Mock(
        return_value=SimpleNamespace(key=key.public_key())
    )
    app.state.object_store = MemoryStore()
    app.state.job_dispatcher = AsyncMock(return_value=True)

    def claims(subject):
        now = int(time.time())
        return {
            "iss": ISSUER,
            "aud": "eduvia-api",
            "sub": subject,
            "iat": now,
            "exp": now + 300,
            CLAIM_NAMESPACE + "email": subject + "@example.com",
            CLAIM_NAMESPACE + "email_verified": True,
        }

    def headers(subject):
        token = jwt.encode(claims(subject), key, algorithm="RS256", headers={"kid": "t"})
        return {"Authorization": "Bearer " + token}

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield SimpleNamespace(client=client, headers=headers, claims=claims, app=app)


async def bootstrap(api, subject):
    await accept_agreements(api.client, api.headers(subject))
    response = await api.client.post("/v1/auth/bootstrap", headers=api.headers(subject))
    assert response.status_code == 200, response.text
    return response.json()["personalWorkspace"]["id"]


async def upload(api, subject, workspace, key=None, body=PDF):
    headers = {
        **api.headers(subject),
        "Content-Type": "application/pdf",
        "X-File-Name": quote("Tài liệu.pdf"),
        "X-Rights-Attested": "true",
    }
    if key:
        headers["Idempotency-Key"] = key
    return await api.client.post(
        f"/v1/workspaces/{workspace}/documents", content=body, headers=headers
    )


async def test_tenant_isolation_for_jobs_and_documents(api, database):
    a, b = "a-" + str(uuid4()), "b-" + str(uuid4())
    wa, wb = await bootstrap(api, a), await bootstrap(api, b)
    created = await upload(api, a, wa)
    assert created.status_code == 202, created.text
    job_id = created.json()["job"]["id"]
    document_id = created.json()["document"]["id"]
    for path in ("/documents", "/jobs", f"/jobs/{job_id}", f"/documents/{document_id}"):
        assert (
            await api.client.get(f"/v1/workspaces/{wa}{path}", headers=api.headers(b))
        ).status_code == 404
    assert (
        await api.client.get(f"/v1/workspaces/{wb}/jobs/{job_id}", headers=api.headers(b))
    ).status_code == 404
    own = await api.client.get(f"/v1/workspaces/{wb}/documents", headers=api.headers(b))
    assert own.status_code == 200 and own.json()["items"] == []
    # Spoofing the workspace GUC without membership still yields no rows.
    async with api.app.state.infrastructure.sessions() as session:
        async with session.begin():
            await session.execute(
                text(
                    "SELECT set_config('edu.issuer', :i, true), "
                    "set_config('edu.subject', :s, true), "
                    "set_config('edu.current_workspace_id', :w, true)"
                ),
                {"i": ISSUER, "s": b, "w": wa},
            )
            for table in ("background_jobs", "documents", "usage_events", "workspace_quotas"):
                assert await session.scalar(text(f"SELECT count(*) FROM edu.{table}")) == 0
    # Runtime cannot delete ledger rows or raise its own cap.
    async with api.app.state.infrastructure.sessions() as session:
        for statement in (
            "DELETE FROM edu.usage_events",
            "UPDATE edu.usage_events SET units = 0",
            "UPDATE edu.workspace_quotas SET month_cap_units = 999999",
            "DELETE FROM edu.background_jobs",
        ):
            with pytest.raises(Exception, match="permission denied"):
                async with session.begin():
                    await session.execute(text(statement))


async def test_duplicate_idempotency_key_returns_same_job(api, database):
    subject = "idem-" + str(uuid4())
    workspace = await bootstrap(api, subject)
    first, second = await asyncio.gather(
        upload(api, subject, workspace, key="same-key"),
        upload(api, subject, workspace, key="same-key"),
    )
    assert first.status_code == second.status_code == 202, (first.text, second.text)
    assert first.json()["job"]["id"] == second.json()["job"]["id"]
    assert first.json()["document"]["id"] == second.json()["document"]["id"]
    conflict = await upload(api, subject, workspace, key="same-key", body=PDF + b"changed")
    assert conflict.status_code == 409
    with database.connect() as db:
        assert (
            db.scalar(
                text("SELECT count(*) FROM edu.background_jobs WHERE workspace_id=:w"),
                {"w": workspace},
            )
            == 1
        )
        assert (
            db.scalar(
                text("SELECT count(*) FROM edu.documents WHERE workspace_id=:w"), {"w": workspace}
            )
            == 1
        )
    assert len(api.app.state.object_store.objects) >= 1


async def test_quota_cap_blocks_concurrent_overflow(api, database):
    subject = "quota-" + str(uuid4())
    workspace = UUID(await bootstrap(api, subject))
    with database.begin() as db:
        db.execute(
            text("UPDATE edu.workspace_quotas SET month_cap_units=3 WHERE workspace_id=:w"),
            {"w": workspace},
        )
    claims = api.claims(subject)
    sessions = api.app.state.infrastructure.sessions

    async def reserve(delay):
        await asyncio.sleep(delay)
        async with sessions() as session:
            try:
                async with workspace_transaction(session, claims, workspace) as scope:
                    await usage.reserve(session, scope, 2)
                    await asyncio.sleep(0.3)  # hold the quota row lock
                return "ok"
            except ApiError as exc:
                return exc.code

    results = await asyncio.gather(reserve(0), reserve(0.05))
    assert sorted(results) == ["ok", "quota_exceeded"]
    with database.connect() as db:
        assert (
            db.scalar(
                text("SELECT sum(units) FROM edu.usage_events WHERE workspace_id=:w"),
                {"w": workspace},
            )
            == 2
        )


async def test_worker_executes_under_job_context_and_sweeper_recovers(api, database):
    from app.tasks.jobs import execute_job, sweep_jobs

    subject = "worker-" + str(uuid4())
    workspace = await bootstrap(api, subject)
    created = await upload(api, subject, workspace)
    job_id = UUID(created.json()["job"]["id"])
    engine = create_engine(runtime_url())
    sessions = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    sent = []
    try:
        store = api.app.state.object_store
        send = lambda *args, **kwargs: sent.append(args)  # noqa: E731
        assert execute_job(job_id, sessions=sessions, store=store, send=send) == "succeeded"
        assert execute_job(job_id, sessions=sessions, store=store, send=send) == "not_claimed"
        with database.connect() as db:
            status = db.execute(
                text(
                    "SELECT j.status, d.status FROM edu.background_jobs j "
                    "JOIN edu.documents d ON d.id::text = j.input->>'documentId' WHERE j.id=:id"
                ),
                {"id": job_id},
            ).one()
        assert tuple(status) == ("succeeded", "uploaded")

        second = await upload(api, subject, workspace, body=PDF + b"2")
        stuck = UUID(second.json()["job"]["id"])
        with database.begin() as db:
            db.execute(
                text(
                    "UPDATE edu.background_jobs SET status='running', attempt=1, "
                    "lease_expires_at=clock_timestamp() - interval '1 minute' WHERE id=:id"
                ),
                {"id": stuck},
            )
        outcomes = sweep_jobs(sessions=sessions, send=send)
        assert any(o.job_id == stuck and o.action == "requeued" for o in outcomes)
        assert (stuck, "document.ingest") in sent
    finally:
        engine.dispose()
