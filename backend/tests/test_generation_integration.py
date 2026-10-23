"""Real PostgreSQL checks for 0010 (disposable *_test database, AUTH_TEST_DATABASE_URL).

Covers: migration to head; ``exam_answer_keys`` has no runtime SELECT while
``edu.exam_item_key`` returns the key to a teacher (NULL to a non-member);
``edu.exam_keys_for_scoring`` is denied for a non-published version and works once published;
the publication trigger re-validates; published versions/items/keys are immutable; and the
worker runs ``questions.generate`` (fake provider) and ``export.render`` under the job actor.
"""

import io
import os
import time
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
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

from app.api import authoring as authoring_api
from app.api import generation as generation_api
from app.core.auth import CLAIM_NAMESPACE
from app.core.config import Settings, get_settings
from app.main import create_app
from app.services import llm

ADMIN_URL = os.getenv("AUTH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="Set AUTH_TEST_DATABASE_URL to disposable PostgreSQL"
)
ISSUER = "https://identity.example/"


def question_payload(key, unit=None):
    payload = {
        "stem": f"Câu hỏi kiểm tra {uuid4()}",
        "choices": [{"key": k, "text": f"Phương án {k}"} for k in "ABCD"],
        "correctKey": key,
        "explanation": "Giải thích dành cho giáo viên.",
        "cognitiveLevel": "remember",
    }
    if unit:
        payload["curriculumUnitId"] = unit
    return payload


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


@pytest.fixture
def runtime(database):
    engine = create_engine(runtime_url())
    yield engine
    engine.dispose()


class MemoryStore:
    def __init__(self):
        self.objects = {}

    def put(self, key, body, *, mime, size, sha256):
        self.objects[key] = body.read()

    def presign_get(self, key, *, file_name, mime, ttl_seconds=60):
        return "https://signed.example/" + file_name, None


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
    for router in (authoring_api.router, generation_api.router):
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


async def bootstrap(api, subject):
    response = await api.client.post("/v1/auth/bootstrap", headers=api.headers(subject))
    assert response.status_code == 200, response.text
    return response.json()["personalWorkspace"]["id"]


def as_actor(connection, subject, workspace):
    connection.execute(
        text(
            "SELECT set_config('edu.issuer', :issuer, true), "
            "set_config('edu.subject', :subject, true), "
            "set_config('edu.current_workspace_id', :workspace, true)"
        ),
        {"issuer": ISSUER, "subject": subject, "workspace": str(workspace)},
    )


async def manual_exam(api, subject, workspace):
    ids = []
    for key in ("B", "C"):
        created = await api.client.post(
            f"/v1/workspaces/{workspace}/questions",
            json=question_payload(key),
            headers=api.headers(subject),
        )
        assert created.status_code == 201, created.text
        ids.append(created.json()["id"])
    exam = await api.client.post(
        f"/v1/workspaces/{workspace}/exams",
        json={"title": "Đề kiểm tra", "questionIds": ids, "points": ["4.00", "6.00"]},
        headers=api.headers(subject),
    )
    assert exam.status_code == 201, exam.text
    return exam.json()


async def test_exam_keys_are_only_readable_through_functions(api, runtime):
    a, b = "exam-a-" + str(uuid4()), "exam-b-" + str(uuid4())
    wa, _ = await bootstrap(api, a), await bootstrap(api, b)
    exam = await manual_exam(api, a, wa)
    assert [i["correctKey"] for i in exam["currentVersion"]["items"]] == ["B", "C"]
    item_id = exam["currentVersion"]["items"][0]["id"]
    version_id = exam["currentVersion"]["id"]

    with pytest.raises(DBAPIError) as denied:
        with runtime.begin() as connection:
            as_actor(connection, a, wa)
            connection.execute(text("SELECT correct_key FROM edu.exam_answer_keys"))
    assert denied.value.orig.sqlstate == "42501"

    with runtime.begin() as connection:
        as_actor(connection, a, wa)
        assert (
            connection.execute(text("SELECT edu.exam_item_key(:i)"), {"i": item_id}).scalar() == "B"
        )
    with runtime.begin() as connection:
        as_actor(connection, b, wa)  # non-member spoofing the workspace context
        assert (
            connection.execute(text("SELECT edu.exam_item_key(:i)"), {"i": item_id}).scalar()
            is None
        )

    with pytest.raises(DBAPIError) as unpublished:
        with runtime.begin() as connection:
            as_actor(connection, a, wa)
            connection.execute(
                text("SELECT * FROM edu.exam_keys_for_scoring(:v)"), {"v": version_id}
            ).all()
    assert unpublished.value.orig.sqlstate == "42501"

    view = await api.client.get(
        f"/v1/workspaces/{wa}/exams/{exam['id']}/versions/1/student-view", headers=api.headers(a)
    )
    assert view.status_code == 200 and "correctKey" not in view.text
    assert "Giải thích" not in view.text

    published = await api.client.post(
        f"/v1/workspaces/{wa}/exams/{exam['id']}/versions/1/publish", headers=api.headers(a)
    )
    assert published.status_code == 200, published.text
    with runtime.begin() as connection:
        as_actor(connection, a, wa)
        rows = connection.execute(
            text("SELECT * FROM edu.exam_keys_for_scoring(:v)"), {"v": version_id}
        ).all()
    assert [(r.correct_key, float(r.points)) for r in rows] == [("B", 4.0), ("C", 6.0)]
    with pytest.raises(DBAPIError):
        with runtime.begin() as connection:
            as_actor(connection, b, wa)
            connection.execute(
                text("SELECT * FROM edu.exam_keys_for_scoring(:v)"), {"v": version_id}
            ).all()


async def test_published_snapshot_is_immutable_and_publication_revalidated(api, runtime):
    a = "imm-exam-" + str(uuid4())
    wa = await bootstrap(api, a)
    exam = await manual_exam(api, a, wa)
    version_id = exam["currentVersion"]["id"]

    # Database-level publication validation (bypassing the service check).
    publish_sql = text(
        "UPDATE edu.exam_versions SET status = 'published', "
        "published_at = clock_timestamp(), published_by_user_id = edu.actor_id(), "
        "content_hash = decode(repeat('00', 32), 'hex') WHERE id = :v"
    )
    with runtime.begin() as connection:
        as_actor(connection, a, wa)
        connection.execute(
            text("UPDATE edu.exam_versions SET total_points = 99 WHERE id = :v"),
            {"v": version_id},
        )
    with pytest.raises(DBAPIError) as mismatch:
        with runtime.begin() as connection:
            as_actor(connection, a, wa)
            connection.execute(publish_sql, {"v": version_id})
    assert mismatch.value.orig.sqlstate == "23514"
    assert "points_mismatch" in str(mismatch.value.orig)
    with runtime.begin() as connection:
        as_actor(connection, a, wa)
        connection.execute(
            text("UPDATE edu.exam_versions SET total_points = 10 WHERE id = :v"),
            {"v": version_id},
        )

    response = await api.client.post(
        f"/v1/workspaces/{wa}/exams/{exam['id']}/versions/1/publish", headers=api.headers(a)
    )
    assert response.status_code == 200, response.text
    for statement, state in (
        ("UPDATE edu.exam_versions SET total_points = 10.5 WHERE id = :v", "23514"),
        ("UPDATE edu.exam_versions SET status = 'draft' WHERE id = :v", "23514"),
        ("UPDATE edu.exam_items SET stem = 'đổi' WHERE exam_version_id = :v", "42501"),
        (
            "INSERT INTO edu.exam_items(workspace_id, exam_version_id, position, stem, choices,"
            ' points) SELECT workspace_id, id, 9, \'mới\', \'[{"key":"A","text":"1"},'
            '{"key":"B","text":"2"},{"key":"C","text":"3"}]\'::jsonb, 1'
            " FROM edu.exam_versions WHERE id = :v",
            "23514",
        ),
    ):
        with pytest.raises(DBAPIError) as error:
            with runtime.begin() as connection:
                as_actor(connection, a, wa)
                connection.execute(text(statement), {"v": version_id})
        assert error.value.orig.sqlstate == state, statement
    with runtime.begin() as connection:
        as_actor(connection, a, wa)
        connection.execute(
            text("UPDATE edu.exam_versions SET status = 'archived' WHERE id = :v"),
            {"v": version_id},
        )


async def test_worker_generates_draft_questions_and_exports(api, database, runtime):
    from app.tasks.jobs import execute_job

    a = "worker-gen-" + str(uuid4())
    wa = await bootstrap(api, a)
    units = await api.client.get(
        "/v1/curriculum/units?subject=toan&grade=10", headers=api.headers(a)
    )
    unit = units.json()["items"][0]["id"]
    requested = await api.client.post(
        f"/v1/workspaces/{wa}/generation/drafts",
        json={
            "purpose": "questions",
            "curriculumUnitId": unit,
            "grade": 10,
            "subject": "Toán",
            "objectives": ["Tập hợp"],
            "count": 2,
        },
        headers=api.headers(a),
    )
    assert requested.status_code == 202, requested.text
    job_id = UUID(requested.json()["job"]["id"])
    engine = create_engine(runtime_url())
    sessions = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    store = api.app.state.object_store
    send = lambda *args, **kwargs: None  # noqa: E731
    try:
        outcome = execute_job(
            job_id, sessions=sessions, store=store, send=send, llm_provider=llm.FakeLLMProvider()
        )
        assert outcome == "succeeded"
        generation_id = requested.json()["generationJob"]["id"]
        fetched = await api.client.get(
            f"/v1/workspaces/{wa}/generation/jobs/{generation_id}", headers=api.headers(a)
        )
        data = fetched.json()
        assert data["validationStatus"] in {"valid", "invalid"} and len(data["questionIds"]) == 2
        with runtime.begin() as connection:
            as_actor(connection, a, wa)
            statuses = connection.execute(
                text("SELECT DISTINCT status FROM edu.questions")
            ).scalars()
            assert set(statuses) == {"draft"}

        exam = await manual_exam(api, a, wa)
        export = await api.client.post(
            f"/v1/workspaces/{wa}/exports",
            json={
                "examVersionId": exam["currentVersion"]["id"],
                "format": "docx",
                "audience": "teacher",
            },
            headers=api.headers(a),
        )
        assert export.status_code == 202, export.text
        export_job = UUID(export.json()["job"]["id"])
        assert execute_job(export_job, sessions=sessions, store=store, send=send) == "succeeded"
        export_id = export.json()["exportJob"]["id"]
        key = f"ws/{wa}/export/{export_id}.docx"
        with zipfile.ZipFile(io.BytesIO(store.objects[key])) as archive:
            xml = archive.read("word/document.xml").decode("utf-8")
        assert "Đáp án: B" in xml
        status = await api.client.get(
            f"/v1/workspaces/{wa}/exports/{export_id}", headers=api.headers(a)
        )
        assert status.json()["status"] == "succeeded" and status.json()["downloadUrl"]

        pdf = await api.client.post(
            f"/v1/workspaces/{wa}/exports",
            json={
                "examVersionId": exam["currentVersion"]["id"],
                "format": "pdf",
                "audience": "teacher",
            },
            headers=api.headers(a),
        )
        pdf_job = UUID(pdf.json()["job"]["id"])
        assert execute_job(pdf_job, sessions=sessions, store=store, send=send) == "failed"
        failed = await api.client.get(
            f"/v1/workspaces/{wa}/exports/{pdf.json()['exportJob']['id']}", headers=api.headers(a)
        )
        assert failed.json()["errorCode"] == "pdf_unicode_unsupported"
    finally:
        engine.dispose()
