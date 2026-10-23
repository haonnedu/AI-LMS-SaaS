"""Real PostgreSQL checks for 0007 knowledge tables (disposable *_test database).

Covers: migration to head with seeds, catalog read-only for the runtime role, tenant isolation of
versions/chunks/tags under the runtime role, the partial unique ``active`` index, immutability
triggers, and that a failed re-ingest never replaces the active version.
"""

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
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.api import documents as documents_api
from app.api import jobs as jobs_api
from app.api import knowledge as knowledge_api
from app.core.auth import CLAIM_NAMESPACE
from app.core.config import Settings, get_settings
from app.main import create_app
from app.services import parsing

ADMIN_URL = os.getenv("AUTH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="Set AUTH_TEST_DATABASE_URL to disposable PostgreSQL"
)
ISSUER = "https://identity.example/"
BODY = (
    "Chương 1. Mệnh đề và tập hợp\n"
    "Mệnh đề là một câu khẳng định đúng hoặc một câu khẳng định sai. "
    "Một mệnh đề không thể vừa đúng vừa sai.\n"
    "Bài 2. Tập hợp là một khái niệm cơ bản của toán học."
).encode()


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
    def __init__(self):
        self.objects = {}

    async def aput(self, key, body, *, mime, size, sha256):
        self.objects[key] = body.read()

    async def adelete(self, key):
        self.objects.pop(key, None)

    def head(self, key):
        return {"ContentLength": len(self.objects[key])} if key in self.objects else None

    def get_bytes(self, key, *, max_bytes):
        return self.objects[key]

    def delete(self, key):
        self.objects.pop(key, None)


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
    for router in (documents_api.router, jobs_api.router, knowledge_api.router):
        if not any(route.path in paths for route in router.routes):
            app.include_router(router)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.token_verifier.jwks.get_signing_key_from_jwt = Mock(
        return_value=SimpleNamespace(key=key.public_key())
    )
    app.state.object_store = MemoryStore()
    app.state.job_dispatcher = AsyncMock(return_value=True)

    def headers(subject):
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": "eduvia-api",
            "sub": subject,
            "iat": now,
            "exp": now + 300,
            CLAIM_NAMESPACE + "email": subject + "@example.com",
            CLAIM_NAMESPACE + "email_verified": True,
        }
        token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "t"})
        return {"Authorization": "Bearer " + token}

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield SimpleNamespace(client=client, headers=headers, app=app)


@pytest.fixture
def worker(database):
    from app.tasks.jobs import execute_job

    engine = create_engine(runtime_url())
    sessions = sessionmaker(engine, expire_on_commit=False, autoflush=False)

    def run(api, job_id):
        return execute_job(
            UUID(job_id),
            sessions=sessions,
            store=api.app.state.object_store,
            send=lambda *args, **kwargs: None,
            max_bytes=1024 * 1024,
        )

    yield run
    engine.dispose()


async def bootstrap(api, subject):
    await accept_agreements(api.client, api.headers(subject))
    response = await api.client.post("/v1/auth/bootstrap", headers=api.headers(subject))
    assert response.status_code == 200, response.text
    return response.json()["personalWorkspace"]["id"]


async def upload_and_ingest(api, worker, subject, workspace, body=BODY):
    response = await api.client.post(
        f"/v1/workspaces/{workspace}/documents",
        content=body,
        headers={
            **api.headers(subject),
            "Content-Type": "text/plain",
            "X-File-Name": quote("Ôn tập.txt"),
            "X-Rights-Attested": "true",
        },
    )
    assert response.status_code == 202, response.text
    assert worker(api, response.json()["job"]["id"]) == "succeeded"
    return response.json()["document"]["id"]


async def test_seeded_catalog_is_read_only_for_runtime(api, database):
    subject = "cat-" + str(uuid4())
    await bootstrap(api, subject)
    units = await api.client.get(
        "/v1/curriculum/units?subject=toan&grade=12", headers=api.headers(subject)
    )
    assert units.status_code == 200, units.text
    assert len(units.json()["items"]) == 5
    subjects = await api.client.get("/v1/curriculum/subjects", headers=api.headers(subject))
    assert {s["code"] for s in subjects.json()["items"]} == {"toan", "ngu-van", "tieng-anh"}
    async with api.app.state.infrastructure.sessions() as session:
        for statement in (
            "INSERT INTO edu.curriculum_subjects(code, name_vi) VALUES ('x', 'X')",
            "UPDATE edu.curriculum_units SET title_vi = 'x'",
            "DELETE FROM edu.curriculum_units",
        ):
            with pytest.raises(Exception, match="permission denied"):
                async with session.begin():
                    await session.execute(text(statement))


async def test_tenant_isolation_for_versions_chunks_and_tags(api, database, worker):
    a, b = "ka-" + str(uuid4()), "kb-" + str(uuid4())
    wa, wb = await bootstrap(api, a), await bootstrap(api, b)
    document = await upload_and_ingest(api, worker, a, wa)
    versions = await api.client.get(
        f"/v1/workspaces/{wa}/documents/{document}/versions", headers=api.headers(a)
    )
    assert versions.status_code == 200, versions.text
    (version,) = versions.json()["items"]
    assert version["status"] == "active" and version["chunkCount"] >= 1
    assert versions.json()["activeVersionId"] == version["id"]
    chunks = await api.client.get(
        f"/v1/workspaces/{wa}/documents/{document}/versions/{version['id']}/chunks",
        headers=api.headers(a),
    )
    assert chunks.status_code == 200 and chunks.json()["items"][0]["text"].startswith("Chương 1")
    units = (await api.client.get("/v1/curriculum/units", headers=api.headers(a))).json()["items"]
    tagged = await api.client.put(
        f"/v1/workspaces/{wa}/documents/{document}/curriculum-tags",
        json={"unitIds": [units[0]["id"]]},
        headers=api.headers(a),
    )
    assert tagged.status_code == 200, tagged.text

    for path in (
        f"/documents/{document}/versions",
        f"/documents/{document}/versions/{version['id']}/chunks",
        f"/documents/{document}/curriculum-tags",
    ):
        for workspace in (wa, wb):
            response = await api.client.get(
                f"/v1/workspaces/{workspace}{path}", headers=api.headers(b)
            )
            assert response.status_code == 404, (workspace, path)
    # Spoofed workspace GUC without membership: RLS hides every knowledge row.
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
            for table in ("document_versions", "document_chunks", "document_curriculum_tags"):
                assert await session.scalar(text(f"SELECT count(*) FROM edu.{table}")) == 0
    # Runtime can never rewrite or delete chunks or versions.
    async with api.app.state.infrastructure.sessions() as session:
        for statement in (
            "UPDATE edu.document_chunks SET text = 'x'",
            "DELETE FROM edu.document_chunks",
            "DELETE FROM edu.document_versions",
        ):
            with pytest.raises(Exception, match="permission denied"):
                async with session.begin():
                    await session.execute(text(statement))


async def test_active_version_invariants_are_enforced_by_database(api, database, worker):
    subject = "kinv-" + str(uuid4())
    workspace = await bootstrap(api, subject)
    document = await upload_and_ingest(api, worker, subject, workspace)
    with database.connect() as db:
        active = db.execute(
            text(
                "SELECT id, workspace_id FROM edu.document_versions "
                "WHERE document_id = :d AND status = 'active'"
            ),
            {"d": document},
        ).one()
    insert_second_active = text(
        "INSERT INTO edu.document_versions(workspace_id, document_id, version_no, status, parser,"
        " parser_version, chunker_version, text_sha256, activated_at) VALUES (:w, :d, 99,"
        " 'active', 'text', '1', '1', decode(repeat('ab', 32), 'hex'), clock_timestamp())"
    )
    with pytest.raises(DBAPIError, match="uq_document_versions_active"):
        with database.begin() as db:
            db.execute(insert_second_active, {"w": active.workspace_id, "d": document})
    with pytest.raises(DBAPIError, match="immutable"):
        with database.begin() as db:
            db.execute(
                text("UPDATE edu.document_versions SET char_count = 1 WHERE id = :id"),
                {"id": active.id},
            )
    with pytest.raises(DBAPIError, match="processing version"):
        with database.begin() as db:
            db.execute(
                text(
                    "INSERT INTO edu.document_chunks(workspace_id, document_version_id,"
                    " chunk_index, char_start, char_end, text, text_sha256, token_estimate)"
                    " VALUES (:w, :v, 999, 0, 1, 'x', decode(repeat('ab', 32), 'hex'), 1)"
                ),
                {"w": active.workspace_id, "v": active.id},
            )
    with pytest.raises(DBAPIError, match="ck_documents_rights_scope"):
        with database.begin() as db:
            db.execute(
                text("UPDATE edu.documents SET rights_scope = 'shared' WHERE id = :d"),
                {"d": document},
            )


async def test_failed_reingest_does_not_replace_active(api, database, worker, monkeypatch):
    subject = "kfail-" + str(uuid4())
    workspace = await bootstrap(api, subject)
    document = await upload_and_ingest(api, worker, subject, workspace)
    base = f"/v1/workspaces/{workspace}/documents/{document}"
    before = (await api.client.get(base + "/versions", headers=api.headers(subject))).json()

    def broken(_data):
        raise parsing.MalformedDocument("malformed_document")

    monkeypatch.setitem(parsing.PARSERS, "text/plain", parsing.Parser("text", "2", broken))
    queued = await api.client.post(base + "/reingest", headers=api.headers(subject))
    assert queued.status_code == 202, queued.text
    assert worker(api, queued.json()["job"]["id"]) == "failed"

    after = (await api.client.get(base + "/versions", headers=api.headers(subject))).json()
    assert after["activeVersionId"] == before["activeVersionId"]
    assert [(v["versionNo"], v["status"], v["errorCode"]) for v in after["items"]] == [
        (2, "failed", "malformed_document"),
        (1, "active", None),
    ]
    with database.connect() as db:
        orphan_chunks = db.scalar(
            text(
                "SELECT count(*) FROM edu.document_chunks c JOIN edu.document_versions v"
                " ON v.id = c.document_version_id WHERE v.document_id = :d AND v.status <> 'active'"
            ),
            {"d": document},
        )
        status = db.scalar(text("SELECT status FROM edu.documents WHERE id = :d"), {"d": document})
    assert orphan_chunks == 0 and status == "uploaded"

    # A working parser with a newer version supersedes v1 atomically.
    monkeypatch.setitem(
        parsing.PARSERS, "text/plain", parsing.Parser("text", "3", parsing.parse_text)
    )
    again = await api.client.post(
        base + "/reingest", headers={**api.headers(subject), "Idempotency-Key": "v3"}
    )
    assert worker(api, again.json()["job"]["id"]) == "succeeded"
    final = (await api.client.get(base + "/versions", headers=api.headers(subject))).json()
    assert [(v["versionNo"], v["status"]) for v in final["items"]] == [
        (3, "active"),
        (2, "failed"),
        (1, "superseded"),
    ]
    assert final["activeVersionId"] == final["items"][0]["id"]
