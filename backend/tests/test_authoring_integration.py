"""Real PostgreSQL checks for 0009 authoring tables (disposable *_test database).

Covers: migration to head, tenant isolation of content/questions/blueprints through the API and
under the runtime role, ``question_keys`` having no runtime SELECT while ``edu.question_key``
returns the key to a teacher of the workspace and NULL to a non-member, and the immutability
triggers on submitted/published content revisions and published blueprint versions.
"""

import csv
import io
import os
import time
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

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

from app.api import authoring as authoring_api
from app.core.auth import CLAIM_NAMESPACE
from app.core.config import Settings, get_settings
from app.main import create_app

ADMIN_URL = os.getenv("AUTH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="Set AUTH_TEST_DATABASE_URL to disposable PostgreSQL"
)
ISSUER = "https://identity.example/"
BODY = {"sections": [{"heading": "Mục tiêu", "blocks": [{"type": "objective", "text": "Hiểu"}]}]}
QUESTION = {
    "stem": "Tập hợp rỗng có bao nhiêu phần tử?",
    "choices": [{"key": "A", "text": "0"}, {"key": "B", "text": "1"}, {"key": "C", "text": "2"}],
    "correctKey": "A",
    "explanation": "Không có phần tử nào.",
    "cognitiveLevel": "remember",
}


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
    if not any(route.path in paths for route in authoring_api.router.routes):
        app.include_router(authoring_api.router)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.token_verifier.jwks.get_signing_key_from_jwt = Mock(
        return_value=SimpleNamespace(key=key.public_key())
    )

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
    await accept_agreements(api.client, api.headers(subject))
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


async def test_tenant_isolation_api_and_runtime(api, runtime):
    a, b = "auth-a-" + str(uuid4()), "auth-b-" + str(uuid4())
    wa, wb = await bootstrap(api, a), await bootstrap(api, b)
    item = await api.client.post(
        f"/v1/workspaces/{wa}/content-items",
        json={"kind": "lesson_plan", "title": "Giáo án A", "body": BODY},
        headers=api.headers(a),
    )
    assert item.status_code == 201, item.text
    question = await api.client.post(
        f"/v1/workspaces/{wa}/questions", json=QUESTION, headers=api.headers(a)
    )
    assert question.status_code == 201, question.text
    item_id, question_id = item.json()["id"], question.json()["id"]

    for url in (
        f"/v1/workspaces/{wa}/content-items/{item_id}",
        f"/v1/workspaces/{wa}/questions/{question_id}",
    ):
        response = await api.client.get(url, headers=api.headers(b))
        assert response.status_code == 404
    for url, code in (
        (f"/v1/workspaces/{wb}/content-items/{item_id}", "content_not_found"),
        (f"/v1/workspaces/{wb}/questions/{question_id}", "question_not_found"),
    ):
        response = await api.client.get(url, headers=api.headers(b))
        assert response.status_code == 404 and response.json()["error"]["code"] == code

    with runtime.begin() as connection:
        as_actor(connection, b, wa)  # spoofed workspace GUC without membership
        for table in ("content_items", "content_revisions", "questions", "question_revisions"):
            assert connection.execute(text(f"SELECT count(*) FROM edu.{table}")).scalar() == 0
    with runtime.begin() as connection:
        as_actor(connection, a, wa)
        assert connection.execute(text("SELECT count(*) FROM edu.questions")).scalar() == 1


async def test_question_keys_only_via_definer_function(api, runtime):
    a, b = "keys-a-" + str(uuid4()), "keys-b-" + str(uuid4())
    wa, _ = await bootstrap(api, a), await bootstrap(api, b)
    created = await api.client.post(
        f"/v1/workspaces/{wa}/questions", json=QUESTION, headers=api.headers(a)
    )
    assert created.status_code == 201, created.text
    assert created.json()["correctKey"] == "A"
    revision_id = created.json()["revisionId"]

    with pytest.raises(DBAPIError) as denied:
        with runtime.begin() as connection:
            as_actor(connection, a, wa)
            connection.execute(text("SELECT correct_key FROM edu.question_keys"))
    assert denied.value.orig.sqlstate == "42501"  # insufficient_privilege, even for the owner

    with runtime.begin() as connection:
        as_actor(connection, a, wa)
        key = connection.execute(text("SELECT edu.question_key(:r)"), {"r": revision_id}).scalar()
        assert key == "A"
    with runtime.begin() as connection:
        as_actor(connection, b, wa)  # non-member pretending to be in workspace A
        assert (
            connection.execute(text("SELECT edu.question_key(:r)"), {"r": revision_id}).scalar()
            is None
        )

    student = await api.client.get(
        f"/v1/workspaces/{wa}/questions/export?audience=student", headers=api.headers(a)
    )
    rows = list(csv.reader(io.StringIO(student.content.decode("utf-8-sig"))))
    assert "correct" not in rows[0] and len(rows) == 2
    assert "Không có phần tử nào." not in student.text
    teacher = await api.client.get(
        f"/v1/workspaces/{wa}/questions/export?audience=teacher", headers=api.headers(a)
    )
    rows = list(csv.reader(io.StringIO(teacher.content.decode("utf-8-sig"))))
    assert rows[1][rows[0].index("correct")] == "A"

    changed = await api.client.put(
        f"/v1/workspaces/{wa}/questions/{created.json()['id']}/key",
        json={"correctKey": "B"},
        headers=api.headers(a),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["correctKey"] == "B" and changed.json()["revisionNo"] == 2


async def test_content_immutability_triggers(api, runtime):
    a = "imm-" + str(uuid4())
    wa = await bootstrap(api, a)
    created = await api.client.post(
        f"/v1/workspaces/{wa}/content-items",
        json={"kind": "study_guide", "title": "Đề cương", "body": BODY},
        headers=api.headers(a),
    )
    item_id = created.json()["id"]
    base = f"/v1/workspaces/{wa}/content-items/{item_id}"
    saved = await api.client.put(
        base + "/draft", json={"body": BODY, "expectedRevisionNo": 1}, headers=api.headers(a)
    )
    assert saved.status_code == 200, saved.text
    for action in ("submit", "approve", "publish"):  # sole staff member may self-approve
        response = await api.client.post(f"{base}/revisions/1/{action}", headers=api.headers(a))
        assert response.status_code == 200, (action, response.text)
    stale = await api.client.post(
        base + "/revisions", json={"body": BODY, "expectedRevisionNo": 0}, headers=api.headers(a)
    )
    assert stale.status_code == 409 and stale.json()["error"]["latestRevisionNo"] == 1
    revision_id = (await api.client.get(base, headers=api.headers(a))).json()["currentRevision"][
        "id"
    ]

    for statement in (
        "UPDATE edu.content_revisions SET body = '{\"sections\": []}'::jsonb WHERE id = :r",
        "UPDATE edu.content_revisions SET status = 'draft' WHERE id = :r",
        "UPDATE edu.content_revisions SET published_at = clock_timestamp() WHERE id = :r",
    ):
        with pytest.raises(DBAPIError) as error:
            with runtime.begin() as connection:
                as_actor(connection, a, wa)
                connection.execute(text(statement), {"r": revision_id})
        assert error.value.orig.sqlstate == "23514", statement
    with runtime.begin() as connection:
        as_actor(connection, a, wa)
        connection.execute(
            text("UPDATE edu.content_revisions SET status = 'archived' WHERE id = :r"),
            {"r": revision_id},
        )
    with pytest.raises(DBAPIError):
        with runtime.begin() as connection:
            as_actor(connection, a, wa)
            connection.execute(
                text(
                    "INSERT INTO edu.content_revisions(workspace_id, content_item_id, revision_no,"
                    " body, status, created_by_user_id, body_sha256)"
                    " SELECT workspace_id, id, 99, '{}'::jsonb, 'published', created_by_user_id,"
                    " decode(repeat('00', 32), 'hex') FROM edu.content_items WHERE id = :i"
                ),
                {"i": item_id},
            )


async def test_blueprint_publish_requires_validated_and_freezes(api, runtime):
    a = "bp-" + str(uuid4())
    wa = await bootstrap(api, a)
    units = await api.client.get(
        "/v1/curriculum/units?subject=toan&grade=10", headers=api.headers(a)
    )
    assert units.status_code == 200, units.text  # seeded by 0007
    first = units.json()["items"][0]
    unit, subject = first["id"], first["subjectId"]
    slot = {
        "index": 1,
        "itemType": "single_choice",
        "points": "10.00",
        "curriculumUnitId": str(unit),
        "cognitiveLevel": "remember",
    }
    body = {
        "parts": [{"code": "P1", "title": "Trắc nghiệm", "slots": [slot]}],
        "matrix": [{"curriculumUnitId": str(unit), "cognitiveLevel": "remember", "count": 1}],
    }
    payload = {
        "title": "Kiểm tra",
        "subjectId": str(subject),
        "grade": 10,
        "examKind": "periodic",
        "durationMinutes": 15,
        "totalPoints": "10.00",
        "effectiveYear": 2026,
        "provenance": "Giáo viên tự soạn",
        "body": {**body, "parts": [{**body["parts"][0], "slots": [{**slot, "itemType": "essay"}]}]},
    }
    created = await api.client.post(
        f"/v1/workspaces/{wa}/blueprints", json=payload, headers=api.headers(a)
    )
    assert created.status_code == 201, created.text
    blueprint_id = created.json()["id"]
    base = f"/v1/workspaces/{wa}/blueprints/{blueprint_id}"
    refused = await api.client.post(base + "/versions/1/publish", headers=api.headers(a))
    assert refused.status_code == 409
    good = await api.client.post(base + "/versions", json={"body": body}, headers=api.headers(a))
    assert good.json()["status"] == "validated", good.text
    published = await api.client.post(base + "/versions/2/publish", headers=api.headers(a))
    assert published.status_code == 200, published.text
    with pytest.raises(DBAPIError) as error:
        with runtime.begin() as connection:
            as_actor(connection, a, wa)
            connection.execute(
                text(
                    "UPDATE edu.blueprint_versions SET validation_report = '{}'::jsonb "
                    "WHERE blueprint_id = :b AND version_no = 2"
                ),
                {"b": blueprint_id},
            )
    assert error.value.orig.sqlstate == "23514"
