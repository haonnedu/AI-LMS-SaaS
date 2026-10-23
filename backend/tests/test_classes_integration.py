"""Real PostgreSQL verification of classes/invitations. Use only a disposable *_test database."""

import asyncio
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

from app.api import classes as classes_api
from app.core.auth import CLAIM_NAMESPACE
from app.core.config import Settings, get_settings
from app.main import create_app

ADMIN_URL = os.getenv("AUTH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="Set AUTH_TEST_DATABASE_URL to disposable PostgreSQL"
)


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
        database_name = engine.dialect.identifier_preparer.quote(engine.url.database)
        db.execute(text(f"GRANT CONNECT ON DATABASE {database_name} TO eduvia_runtime"))
    yield engine
    engine.dispose()


@pytest.fixture
async def api(database):
    classes_api.token_limiter.reset()
    classes_api.ip_limiter.reset()
    url = make_url(ADMIN_URL).set(username="eduvia_runtime", password="runtime_test_only")
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=url.render_as_string(hide_password=False),
        auth_issuer="https://identity.example/",
        auth_audience="eduvia-api",
        auth_jwks_url="https://identity.example/jwks",
        db_pool_size=2,
        db_max_overflow=2,
    )
    app = create_app(settings)
    mount_agreements(app)
    if not any(getattr(r, "path", "").endswith("/classes") for r in app.routes):
        app.include_router(classes_api.router)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.token_verifier.jwks.get_signing_key_from_jwt = Mock(
        return_value=SimpleNamespace(key=key.public_key())
    )

    def headers(subject, name="Người dùng"):
        now = int(time.time())
        claims = {
            "iss": settings.auth_issuer,
            "aud": settings.auth_audience,
            "sub": subject,
            "iat": now,
            "exp": now + 300,
            CLAIM_NAMESPACE + "email": subject + "@example.com",
            CLAIM_NAMESPACE + "email_verified": True,
            CLAIM_NAMESPACE + "name": name,
        }
        return {
            "Authorization": "Bearer "
            + jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})
        }

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, headers, app


async def person(client, headers, prefix, name="Người dùng"):
    subject = prefix + "-" + str(uuid4())
    await accept_agreements(client, headers(subject, name))
    response = await client.post("/v1/auth/bootstrap", headers=headers(subject, name))
    assert response.status_code == 200, response.text
    body = response.json()
    return SimpleNamespace(
        subject=subject,
        id=body["user"]["id"],
        workspace=body["personalWorkspace"]["id"],
        h=headers(subject, name),
    )


async def new_class(client, teacher, name="10A1"):
    response = await client.post(
        f"/v1/workspaces/{teacher.workspace}/classes",
        json={"name": name, "subject": "Toán", "academicYear": "2026-2027"},
        headers=teacher.h,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def invite(client, teacher, class_id, **body):
    response = await client.post(
        f"/v1/workspaces/{teacher.workspace}/classes/{class_id}/invitations",
        json=body,
        headers=teacher.h,
    )
    assert response.status_code == 201, response.text
    return response.json()


def accept(client, user, token):
    return client.post(f"/v1/invitations/{token}/accept", headers=user.h)


async def test_cross_tenant_isolation_and_spoofing(api, database):
    client, headers, app = api
    a = await person(client, headers, "teacher-a")
    b = await person(client, headers, "teacher-b")
    cls = await new_class(client, a)
    created = await invite(client, a, cls["id"], maxUses=2)
    assert "tokenHash" not in created and "token_hash" not in str(created)

    listed = (await client.get(f"/v1/workspaces/{a.workspace}/classes", headers=a.h)).json()
    assert [c["id"] for c in listed["items"]] == [cls["id"]]

    base_b = f"/v1/workspaces/{b.workspace}/classes/{cls['id']}"
    base_a = f"/v1/workspaces/{a.workspace}/classes/{cls['id']}"
    spoof = {**b.h, "X-Workspace-ID": a.workspace, "X-User-ID": a.id}
    for path, method in [
        (base_b, "get"),
        (base_b + "/roster", "get"),
        (base_b + "/invitations", "post"),
        (base_b + "/archive", "post"),
        (base_b + f"/invitations/{created['id']}/revoke", "post"),
        (base_a, "get"),
        (base_a + "/roster", "get"),
        (f"/v1/workspaces/{a.workspace}/classes", "get"),
    ]:
        response = await getattr(client, method)(path, headers=spoof)
        assert response.status_code == 404, (path, response.text)
    assert (await client.get(f"/v1/workspaces/{b.workspace}/classes", headers=b.h)).json()[
        "items"
    ] == []

    # Runtime role with B's verified context cannot read A's rows even without API filters.
    async with app.state.infrastructure.sessions() as session:
        async with session.begin():
            await session.execute(
                text(
                    "SELECT set_config('edu.issuer','https://identity.example/',true),"
                    "set_config('edu.subject',:s,true),"
                    "set_config('edu.current_workspace_id',:w,true)"
                ),
                {"s": b.subject, "w": b.workspace},
            )
            for table in ("classes", "class_teachers", "class_invitations"):
                assert await session.scalar(text(f"SELECT count(*) FROM edu.{table}")) == 0
        async with session.begin():
            # Spoofing the workspace GUC without membership still yields nothing.
            await session.execute(
                text(
                    "SELECT set_config('edu.issuer','https://identity.example/',true),"
                    "set_config('edu.subject',:s,true),"
                    "set_config('edu.current_workspace_id',:w,true)"
                ),
                {"s": b.subject, "w": a.workspace},
            )
            assert await session.scalar(text("SELECT count(*) FROM edu.classes")) == 0
            assert (
                await session.scalar(
                    text("SELECT edu.workspace_staff_role(:w, :u)"),
                    {"w": a.workspace, "u": a.id},
                )
                is None
            )


async def test_single_use_invitation_under_concurrency(api, database):
    client, headers, _ = api
    teacher = await person(client, headers, "teacher")
    s1 = await person(client, headers, "student1", "Học sinh Một")
    s2 = await person(client, headers, "student2", "Học sinh Hai")
    cls = await new_class(client, teacher)
    created = await invite(client, teacher, cls["id"])
    responses = await asyncio.gather(
        accept(client, s1, created["token"]), accept(client, s2, created["token"])
    )
    assert sorted(r.status_code for r in responses) == [200, 410], [r.text for r in responses]
    ok = next(r for r in responses if r.status_code == 200).json()
    assert ok["classId"] == cls["id"] and ok["workspaceId"] == teacher.workspace
    assert ok["className"] == "10A1"
    with database.connect() as db:
        assert (
            db.scalar(
                text("SELECT use_count FROM edu.class_invitations WHERE id=:id"),
                {"id": created["id"]},
            )
            == 1
        )
    roster = (
        await client.get(
            f"/v1/workspaces/{teacher.workspace}/classes/{cls['id']}/roster", headers=teacher.h
        )
    ).json()
    assert roster["counts"] == {"enrolled": 1, "invited": 0, "withdrawn": 0}
    # The student is not a member of the teacher workspace and cannot read the roster.
    winner = s1 if responses[0].status_code == 200 else s2
    path = f"/v1/workspaces/{teacher.workspace}/classes/{cls['id']}/roster"
    assert (await client.get(path, headers=winner.h)).status_code == 404


async def test_expired_revoked_unknown_and_archived(api, database):
    client, headers, _ = api
    teacher = await person(client, headers, "teacher")
    student = await person(client, headers, "student")
    cls = await new_class(client, teacher)
    revoked = await invite(client, teacher, cls["id"])
    response = await client.post(
        f"/v1/workspaces/{teacher.workspace}/classes/{cls['id']}/invitations/"
        f"{revoked['id']}/revoke",
        headers=teacher.h,
    )
    assert response.status_code == 200 and response.json()["revokedAt"]
    assert (await accept(client, student, revoked["token"])).status_code == 410

    expired = await invite(client, teacher, cls["id"])
    with database.begin() as db:
        db.execute(
            text(
                "UPDATE edu.class_invitations SET created_at=now()-interval '2 days', "
                "expires_at=now()-interval '1 day' WHERE id=:id"
            ),
            {"id": expired["id"]},
        )
    assert (await accept(client, student, expired["token"])).status_code == 410
    assert (await accept(client, student, "z" * 43)).status_code == 404

    pending = await invite(client, teacher, cls["id"])
    archived = await client.post(
        f"/v1/workspaces/{teacher.workspace}/classes/{cls['id']}/archive", headers=teacher.h
    )
    assert archived.status_code == 200 and archived.json()["status"] == "archived"
    assert (await accept(client, student, pending["token"])).status_code == 410


async def test_withdrawn_student_cannot_reuse_token(api, database):
    client, headers, _ = api
    teacher = await person(client, headers, "teacher")
    student = await person(client, headers, "student", "Nguyễn Văn A")
    cls = await new_class(client, teacher)
    created = await invite(client, teacher, cls["id"], maxUses=5)
    first = await accept(client, student, created["token"])
    assert first.status_code == 200
    again = await accept(client, student, created["token"])  # idempotent while active
    assert again.status_code == 200 and again.json() == first.json()
    enrollment = first.json()["enrollmentId"]
    base = f"/v1/workspaces/{teacher.workspace}/classes/{cls['id']}"
    withdrawn = await client.post(base + f"/enrollments/{enrollment}/withdraw", headers=teacher.h)
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "withdrawn"
    assert (await accept(client, student, created["token"])).status_code == 409
    roster = (await client.get(base + "/roster", headers=teacher.h)).json()
    assert roster["counts"] == {"enrolled": 0, "invited": 0, "withdrawn": 1}
    assert roster["items"][0]["displayName"] == "Nguyễn Văn A"
    fresh = await invite(client, teacher, cls["id"])
    rejoin = await accept(client, student, fresh["token"])
    assert rejoin.status_code == 200 and rejoin.json()["enrollmentId"] == enrollment
    with database.connect() as db:
        assert (
            db.scalar(text("SELECT count(*) FROM edu.students WHERE user_id=:u"), {"u": student.id})
            == 1
        )


async def test_co_teacher_requires_workspace_membership(api, database):
    client, headers, _ = api
    owner = await person(client, headers, "owner")
    other = await person(client, headers, "other")
    cls = await new_class(client, owner)
    base = f"/v1/workspaces/{owner.workspace}/classes/{cls['id']}"
    response = await client.post(base + "/teachers", json={"userId": other.id}, headers=owner.h)
    assert response.status_code == 404
    with database.begin() as db:
        db.execute(
            text(
                "INSERT INTO edu.workspace_members(workspace_id,user_id,role) "
                "VALUES(:w,:u,'teacher')"
            ),
            {"w": owner.workspace, "u": other.id},
        )
    other_in_owner = {**other.h}
    listed = await client.get(f"/v1/workspaces/{owner.workspace}/classes", headers=other_in_owner)
    assert listed.json()["items"] == []  # class-scoped: not yet a teacher of this class
    added = await client.post(base + "/teachers", json={"userId": other.id}, headers=owner.h)
    assert added.status_code == 201 and added.json()["role"] == "co_teacher"
    listed = await client.get(f"/v1/workspaces/{owner.workspace}/classes", headers=other_in_owner)
    assert [c["id"] for c in listed.json()["items"]] == [cls["id"]]
    assert (await client.post(base + "/archive", headers=other.h)).status_code == 403
    assert (await client.delete(base + f"/teachers/{owner.id}", headers=owner.h)).status_code == 409
    assert (await client.delete(base + f"/teachers/{other.id}", headers=owner.h)).status_code == 204
    assert (await client.get(base, headers=other.h)).status_code == 404
