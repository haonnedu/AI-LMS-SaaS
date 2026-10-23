"""Real PostgreSQL + pgvector checks for 0008 retrieval (disposable *_test database).

Covers: migrate to head; ingest with the LocalHashEmbedder writes vectors and an embedding run;
tenant A's retrieval never returns tenant B's chunks under the runtime role (also with a
spoofed workspace GUC); a deleted document disappears from retrieval, its chunks are purged and
versions withdrawn, and a replayed purge is a no-op; vectors of another model/version are
excluded until a ``document.embed`` job re-embeds them.
"""

import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote
from uuid import UUID, uuid4

import jwt
import pytest
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
from app.api import retrieval as retrieval_api
from app.core.auth import CLAIM_NAMESPACE
from app.core.config import Settings, get_settings
from app.main import create_app
from app.services import retrieval
from app.services.embeddings import LocalHashEmbedder

ADMIN_URL = os.getenv("AUTH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="Set AUTH_TEST_DATABASE_URL to disposable PostgreSQL"
)
ISSUER = "https://identity.example/"
BODY_A = (
    "Chương 1. Mệnh đề và tập hợp\n"
    "Mệnh đề là một câu khẳng định đúng hoặc một câu khẳng định sai. "
    "Một mệnh đề không thể vừa đúng vừa sai. Tài liệu riêng của giáo viên A.\n"
).encode()
BODY_B = (
    "Chương 1. Mệnh đề\n"
    "Mệnh đề là một câu khẳng định đúng hoặc một câu khẳng định sai. "
    "Tài liệu nội bộ của trường B, không được chia sẻ.\n"
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
    paths = {getattr(route, "path", "") for route in app.routes}
    for router in (
        documents_api.router,
        jobs_api.router,
        knowledge_api.router,
        retrieval_api.router,
    ):
        if not any(route.path in paths for route in router.routes):
            app.include_router(router)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.token_verifier.jwks.get_signing_key_from_jwt = Mock(
        return_value=SimpleNamespace(key=key.public_key())
    )
    app.state.object_store = MemoryStore()
    app.state.job_dispatcher = AsyncMock(return_value=True)
    app.state.embedder = LocalHashEmbedder()

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

    def run(api, job_id, embedder=None):
        return execute_job(
            UUID(job_id),
            sessions=sessions,
            store=api.app.state.object_store,
            send=lambda *args, **kwargs: None,
            max_bytes=1024 * 1024,
            embedder=embedder or LocalHashEmbedder(),
        )

    yield run
    engine.dispose()


async def bootstrap(api, subject):
    response = await api.client.post("/v1/auth/bootstrap", headers=api.headers(subject))
    assert response.status_code == 200, response.text
    return response.json()["personalWorkspace"]["id"]


async def upload_and_ingest(api, worker, subject, workspace, body):
    response = await api.client.post(
        f"/v1/workspaces/{workspace}/documents",
        content=body,
        headers={
            **api.headers(subject),
            "Content-Type": "text/plain",
            "X-File-Name": quote("Mệnh đề.txt"),
            "X-Rights-Attested": "true",
        },
    )
    assert response.status_code == 202, response.text
    assert worker(api, response.json()["job"]["id"]) == "succeeded"
    return response.json()["document"]["id"]


async def query(api, subject, workspace, q, **extra):
    return await api.client.post(
        f"/v1/workspaces/{workspace}/retrieval/query",
        json={"query": q, **extra},
        headers=api.headers(subject),
    )


async def test_tenant_a_never_sees_tenant_b_chunks(api, database, worker):
    a, b = "ra-" + str(uuid4()), "rb-" + str(uuid4())
    wa, wb = await bootstrap(api, a), await bootstrap(api, b)
    doc_a = await upload_and_ingest(api, worker, a, wa, BODY_A)
    doc_b = await upload_and_ingest(api, worker, b, wb, BODY_B)

    runs = await api.client.get(
        f"/v1/workspaces/{wa}/documents/{doc_a}/embedding-runs", headers=api.headers(a)
    )
    assert runs.status_code == 200, runs.text
    assert [r["status"] for r in runs.json()["items"]] == ["succeeded"]
    with database.connect() as db:
        models = db.execute(
            text(
                "SELECT DISTINCT c.embedding_model, c.embedding_version FROM edu.document_chunks c"
                " JOIN edu.document_versions v ON v.id = c.document_version_id"
                " WHERE v.document_id = :d"
            ),
            {"d": doc_a},
        ).all()
    assert [tuple(m) for m in models] == [("local-hash-v1", "1024d.r1")]

    response = await query(api, a, wa, "Mệnh đề là một câu khẳng định")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["abstained"] is False and body["mode"] == "hybrid"
    assert {item["documentId"] for item in body["items"]} == {doc_a}
    assert body["items"][0]["citation"] == "[1]"

    # Cross-tenant: B cannot query A's workspace; B's own query never returns A's document.
    assert (await query(api, b, wa, "Mệnh đề")).status_code == 404
    own = (await query(api, b, wb, "Mệnh đề là một câu khẳng định")).json()
    assert {item["documentId"] for item in own["items"]} == {doc_b}
    chunk_a = body["items"][0]["chunkId"]
    cited = await api.client.get(f"/v1/workspaces/{wb}/citations/{chunk_a}", headers=api.headers(b))
    assert cited.status_code == 404

    # Spoofed workspace GUC under the runtime role: RLS leaves nothing to rank.
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
            spoofed = SimpleNamespace(workspace=SimpleNamespace(id=UUID(wa)))
            vector = LocalHashEmbedder().embed(["Mệnh đề"]).vectors[0]
            assert (
                await retrieval.retrieve(
                    session,
                    spoofed,
                    "Mệnh đề",
                    query_vector=vector,
                    model="local-hash-v1",
                    model_version="1024d.r1",
                )
                == []
            )


async def test_deleted_document_disappears_and_purge_replay_is_idempotent(api, database, worker):
    subject = "rdel-" + str(uuid4())
    workspace = await bootstrap(api, subject)
    document = await upload_and_ingest(api, worker, subject, workspace, BODY_A)
    before = (await query(api, subject, workspace, "Mệnh đề là một câu khẳng định")).json()
    assert before["items"]
    chunk_id = before["items"][0]["chunkId"]

    deleted = await api.client.delete(
        f"/v1/workspaces/{workspace}/documents/{document}", headers=api.headers(subject)
    )
    assert deleted.status_code == 202, deleted.text
    job_id = deleted.json()["job"]["id"]
    # Even before the purge job runs, retrieval filters the soft-deleted document out.
    pending = (await query(api, subject, workspace, "Mệnh đề là một câu khẳng định")).json()
    assert pending["items"] == [] and pending["abstained"] is True

    assert worker(api, job_id) == "succeeded"
    with database.connect() as db:
        result = db.scalar(
            text("SELECT result FROM edu.background_jobs WHERE id = :j"), {"j": job_id}
        )
        statuses = db.scalars(
            text("SELECT status FROM edu.document_versions WHERE document_id = :d"),
            {"d": document},
        ).all()
        remaining = db.scalar(
            text(
                "SELECT count(*) FROM edu.document_chunks c JOIN edu.document_versions v"
                " ON v.id = c.document_version_id WHERE v.document_id = :d"
            ),
            {"d": document},
        )
    assert result["deleted"] is True and result["purgedChunks"] >= 1
    assert set(statuses) == {"withdrawn"} and remaining == 0
    assert f"ws/{workspace}/doc/{document}" not in api.app.state.object_store.objects
    cited = await api.client.get(
        f"/v1/workspaces/{workspace}/citations/{chunk_id}", headers=api.headers(subject)
    )
    assert cited.status_code == 404

    # Replay the same job: purges 0 rows, no error, nothing resurrected.
    with database.begin() as db:
        db.execute(
            text(
                "UPDATE edu.background_jobs SET status = 'queued', attempt = 0,"
                " finished_at = NULL WHERE id = :j"
            ),
            {"j": job_id},
        )
    assert worker(api, job_id) == "succeeded"
    with database.connect() as db:
        result = db.scalar(
            text("SELECT result FROM edu.background_jobs WHERE id = :j"), {"j": job_id}
        )
    assert result == {"deleted": True, "purgedChunks": 0}
    with pytest.raises(DBAPIError, match="invalid document version transition"):
        with database.begin() as db:
            db.execute(
                text("UPDATE edu.document_versions SET status = 'active' WHERE document_id = :d"),
                {"d": document},
            )


async def test_purge_requires_owning_context_and_deleted_document(api, database, worker):
    a, b = "rpa-" + str(uuid4()), "rpb-" + str(uuid4())
    wa, wb = await bootstrap(api, a), await bootstrap(api, b)
    document = await upload_and_ingest(api, worker, a, wa, BODY_A)

    async def purge_as(subject, workspace):
        async with api.app.state.infrastructure.sessions() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "SELECT set_config('edu.issuer', :i, true), "
                        "set_config('edu.subject', :s, true), "
                        "set_config('edu.current_workspace_id', :w, true)"
                    ),
                    {"i": ISSUER, "s": subject, "w": workspace},
                )
                return await session.scalar(
                    text("SELECT edu.purge_document_chunks(:d)"), {"d": document}
                )

    with pytest.raises(DBAPIError, match="Document is not deleted"):
        await purge_as(a, wa)  # live document: refuse
    for subject, workspace in ((b, wb), (b, wa)):
        with pytest.raises(DBAPIError, match="Document not found"):
            await purge_as(subject, workspace)
    # Runtime can still never DELETE chunks directly.
    async with api.app.state.infrastructure.sessions() as session:
        with pytest.raises(Exception, match="permission denied"):
            async with session.begin():
                await session.execute(text("DELETE FROM edu.document_chunks"))


async def test_model_version_mismatch_is_excluded_until_reembedded(api, database, worker):
    subject = "rmod-" + str(uuid4())
    workspace = await bootstrap(api, subject)
    document = await upload_and_ingest(api, worker, subject, workspace, BODY_A)
    # "gì" is not in the text, so plainto_tsquery (AND) cannot match: only vectors can.
    semantic_only = "Mệnh đề là gì"
    hit = (await query(api, subject, workspace, semantic_only)).json()
    assert hit["items"] and all(i["sources"] == ["semantic"] for i in hit["items"])

    newer = LocalHashEmbedder(revision="2")
    api.app.state.embedder = newer
    missed = (await query(api, subject, workspace, semantic_only)).json()
    assert missed["items"] == [] and missed["abstained"] is True

    queued = await api.client.post(
        f"/v1/workspaces/{workspace}/documents/{document}/embed", headers=api.headers(subject)
    )
    assert queued.status_code == 202, queued.text
    assert worker(api, queued.json()["job"]["id"], embedder=newer) == "succeeded"
    again = (await query(api, subject, workspace, semantic_only)).json()
    assert again["items"] and again["items"][0]["documentId"] == document
    runs = await api.client.get(
        f"/v1/workspaces/{workspace}/documents/{document}/embedding-runs",
        headers=api.headers(subject),
    )
    assert [(r["version"], r["status"]) for r in runs.json()["items"]] == [
        ("1024d.r2", "succeeded"),
        ("1024d.r1", "succeeded"),
    ]
    # Runtime may only write the embedding triple; chunk text stays immutable.
    async with api.app.state.infrastructure.sessions() as session:
        with pytest.raises(Exception, match="permission denied"):
            async with session.begin():
                await session.execute(text("UPDATE edu.document_chunks SET text = 'x'"))
