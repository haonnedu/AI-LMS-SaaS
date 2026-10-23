"""Real PostgreSQL verification. Use only a disposable database ending in _test."""

import asyncio
import json
import os
import time
from argparse import Namespace
from uuid import uuid4

import jwt
import pytest
from agreements_helper import accept_agreements, mount_agreements
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from app.core.auth import CLAIM_NAMESPACE
from app.core.config import Settings, get_settings
from app.main import create_app

ADMIN_URL = os.getenv("AUTH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="Set AUTH_TEST_DATABASE_URL to disposable PostgreSQL"
)


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    assert ADMIN_URL and ADMIN_URL.rsplit("/", 1)[-1].endswith("_test"), "Test database required"
    engine = create_engine(ADMIN_URL)
    with engine.begin() as db:
        db.execute(text("DROP SCHEMA IF EXISTS auth CASCADE"))
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
        config = Config("alembic.ini")
        command.upgrade(config, "0003_row_level_security")
        legacy_user, legacy_workspace = uuid4(), uuid4()
        with engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO edu.users(id,email,provider_sub) "
                    "VALUES(:id,'legacy@example.com','legacy-sub')"
                ),
                {"id": legacy_user},
            )
            db.execute(
                text("INSERT INTO edu.workspaces(id,name,slug) VALUES(:id,'Legacy','legacy')"),
                {"id": legacy_workspace},
            )
            db.execute(
                text(
                    "INSERT INTO edu.workspace_members(workspace_id,user_id,role) "
                    "VALUES(:workspace,:user,'owner')"
                ),
                {"workspace": legacy_workspace, "user": legacy_user},
            )
        with pytest.raises(RuntimeError, match="explicit UUID-to-issuer"):
            command.upgrade(config, "head")
        with engine.connect() as db:
            assert (
                db.scalar(text("SELECT version_num FROM alembic_version"))
                == "0003_row_level_security"
            )
        mapping = tmp_path_factory.mktemp("identity") / "map.json"
        mapping.write_text(json.dumps({str(legacy_user): "https://legacy.example/"}))
        config.cmd_opts = Namespace(x=["identity_map=" + str(mapping)])
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with engine.connect() as db:
            assert (
                db.scalar(
                    text("SELECT provider_issuer FROM edu.users WHERE id=:id"), {"id": legacy_user}
                )
                == "https://legacy.example/"
            )
            assert (
                db.scalar(
                    text("SELECT personal_owner_user_id FROM edu.workspaces WHERE id=:id"),
                    {"id": legacy_workspace},
                )
                == legacy_user
            )
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
    from types import SimpleNamespace
    from unittest.mock import Mock

    from sqlalchemy.engine import make_url

    url = make_url(ADMIN_URL).set(username="eduvia_runtime", password="runtime_test_only")
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=url.render_as_string(hide_password=False),
        auth_issuer="https://identity.example/",
        auth_audience="eduvia-api",
        auth_jwks_url="https://identity.example/jwks",
        db_pool_size=1,
        db_max_overflow=1,
    )
    app = create_app(settings)
    mount_agreements(app)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.token_verifier.jwks.get_signing_key_from_jwt = Mock(
        return_value=SimpleNamespace(key=key.public_key())
    )

    def headers(subject, verified=True):
        now = int(time.time())
        claims = {
            "iss": settings.auth_issuer,
            "aud": settings.auth_audience,
            "sub": subject,
            "iat": now,
            "exp": now + 300,
            CLAIM_NAMESPACE + "email": subject + "@example.com",
            CLAIM_NAMESPACE + "email_verified": verified,
            CLAIM_NAMESPACE + "name": "Teacher",
        }
        return {
            "Authorization": "Bearer "
            + jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})
        }

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, headers, app


async def test_removed_transfer_endpoint(api):
    client, headers, _ = api
    response = await client.post(
        "/v1/auth/migrate", headers=headers("old-user"), json={"proof": "old"}
    )
    assert response.status_code == 404


async def test_bootstrap_concurrency_and_identity(api, database):
    client, headers, _ = api
    subject = "concurrent-" + str(uuid4())
    assert (await client.get("/v1/me", headers=headers(subject))).status_code == 409
    # Concurrent first acceptances provision the account exactly once (advisory lock).
    await asyncio.gather(*[accept_agreements(client, headers(subject)) for _ in range(2)])
    responses = await asyncio.gather(
        *[client.post("/v1/auth/bootstrap", headers=headers(subject)) for _ in range(2)]
    )
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    assert responses[0].json() == responses[1].json()
    result = responses[0].json()
    assert (await client.get("/v1/me", headers=headers(subject))).json() == result["user"]
    with database.connect() as db:
        assert (
            db.scalar(
                text("SELECT count(*) FROM edu.users WHERE provider_sub=:sub"), {"sub": subject}
            )
            == 1
        )
        assert (
            db.scalar(
                text("SELECT count(*) FROM edu.workspaces WHERE personal_owner_user_id=:id"),
                {"id": result["user"]["id"]},
            )
            == 1
        )


async def test_isolation_revocation_and_pool(api, database):
    client, headers, app = api
    a, b = "a-" + str(uuid4()), "b-" + str(uuid4())
    await accept_agreements(client, headers(a))
    await accept_agreements(client, headers(b))
    ra = (await client.post("/v1/auth/bootstrap", headers=headers(a))).json()
    rb = (await client.post("/v1/auth/bootstrap", headers=headers(b))).json()
    wa, wb = ra["personalWorkspace"]["id"], rb["personalWorkspace"]["id"]
    spoof = {**headers(a), "X-User-ID": rb["user"]["id"], "X-Workspace-ID": wb}
    assert (await client.get("/v1/workspaces/" + wb, headers=spoof)).status_code == 404
    assert (await client.get("/v1/workspaces", headers=headers(a))).json()["items"][0]["id"] == wa
    assert (await client.get("/v1/workspaces", headers=headers(b))).json()["items"][0]["id"] == wb
    async with app.state.infrastructure.sessions() as session:
        async with session.begin():
            assert await session.scalar(text("SELECT count(*) FROM edu.users")) == 0
            assert await session.scalar(text("SELECT count(*) FROM edu.workspace_members")) == 0
    with database.begin() as db:
        db.execute(
            text("UPDATE edu.workspace_members SET status='suspended' WHERE workspace_id=:id"),
            {"id": wa},
        )
    assert (await client.get("/v1/workspaces/" + wa, headers=headers(a))).status_code == 404
    assert (await client.post("/v1/auth/bootstrap", headers=headers(a))).status_code == 403


async def test_unverified_disabled_and_missing_auth(api, database):
    client, headers, _ = api
    subject = "disabled-" + str(uuid4())
    assert (await client.post("/v1/auth/bootstrap")).status_code == 401
    assert (
        await client.post("/v1/auth/bootstrap", headers=headers(subject, False))
    ).status_code == 403
    await accept_agreements(client, headers(subject))
    result = (await client.post("/v1/auth/bootstrap", headers=headers(subject))).json()
    with database.begin() as db:
        db.execute(
            text("UPDATE edu.users SET is_active=false WHERE id=:id"), {"id": result["user"]["id"]}
        )
    assert (await client.get("/v1/me", headers=headers(subject))).status_code == 403
    assert (await client.post("/v1/auth/bootstrap", headers=headers(subject))).status_code == 403


async def test_runtime_cannot_change_roles_and_rollback(api, database):
    from sqlalchemy.exc import DBAPIError

    from app.infrastructure.context import set_identity

    _, _, app = api
    subject = "rollback-" + str(uuid4())
    async with app.state.infrastructure.sessions() as session:
        with pytest.raises(RuntimeError):
            async with session.begin():
                await set_identity(session, "https://identity.example/", subject)
                await session.execute(text("SELECT edu.bootstrap_identity('a@example.com','Name')"))
                raise RuntimeError("simulated failure")
        with pytest.raises(DBAPIError):
            async with session.begin():
                await session.execute(text("UPDATE edu.workspace_members SET role='owner'"))
        for statement in (
            "UPDATE edu.user_identities SET subject='forged'",
            'SELECT id FROM auth."user"',
        ):
            with pytest.raises(DBAPIError):
                async with session.begin():
                    await session.execute(text(statement))
    with database.connect() as db:
        assert (
            db.scalar(text("SELECT count(*) FROM edu.users WHERE provider_sub=:s"), {"s": subject})
            == 0
        )


async def test_issuer_subject_pair_is_not_email_identity(api, database):
    from app.infrastructure.context import set_identity

    _, _, app = api
    subject = "shared-subject-" + str(uuid4())
    ids = []
    async with app.state.infrastructure.sessions() as session:
        for issuer in ("https://first.example/", "https://second.example/"):
            async with session.begin():
                await set_identity(session, issuer, subject)
                ids.append(
                    await session.scalar(
                        text("SELECT edu.bootstrap_identity('same@example.com','Name')")
                    )
                )
    assert ids[0] != ids[1]
    with database.connect() as db:
        assert (
            db.scalar(
                text("SELECT count(*) FROM edu.users WHERE provider_sub=:subject"),
                {"subject": subject},
            )
            == 2
        )


async def test_workspace_pagination_only_returns_own_memberships(api, database):
    client, headers, _ = api
    subject = "pages-" + str(uuid4())
    await accept_agreements(client, headers(subject))
    result = (await client.post("/v1/auth/bootstrap", headers=headers(subject))).json()
    with database.begin() as db:
        for _ in range(2):
            workspace = uuid4()
            db.execute(
                text(
                    "INSERT INTO edu.workspaces(id,name,slug,workspace_type) "
                    "VALUES(:id,'School',:slug,'school')"
                ),
                {"id": workspace, "slug": str(workspace)},
            )
            db.execute(
                text(
                    "INSERT INTO edu.workspace_members(workspace_id,user_id) "
                    "VALUES(:workspace,:user)"
                ),
                {"workspace": workspace, "user": result["user"]["id"]},
            )
    cursor, found = None, []
    while True:
        query = "/v1/workspaces?limit=1" + ("&cursor=" + cursor if cursor else "")
        response = await client.get(query, headers=headers(subject))
        assert response.status_code == 200
        page = response.json()
        found.extend(item["id"] for item in page["items"])
        cursor = page["nextCursor"]
        if not cursor:
            break
    assert len(found) == len(set(found)) == 3
    invalid = await client.get("/v1/workspaces?limit=101", headers=headers(subject))
    assert invalid.status_code == 422
    assert set(invalid.json()) == {"error", "requestId"}


def seed_discardable(database):
    user_id, workspace_id = uuid4(), uuid4()
    with database.begin() as db:
        db.execute(
            text(
                "INSERT INTO edu.users(id,provider_issuer,provider_sub,email) "
                "VALUES(:id,'https://retired.auth0.com/', :sub,'test@example.test')"
            ),
            {"id": user_id, "sub": "auth0|" + str(user_id)},
        )
        db.execute(
            text(
                "INSERT INTO edu.user_identities(issuer,subject,user_id) "
                "VALUES('https://retired.auth0.com/',:sub,:id)"
            ),
            {"id": user_id, "sub": "auth0|" + str(user_id)},
        )
        db.execute(
            text(
                "INSERT INTO edu.workspaces(id,name,slug,personal_owner_user_id) "
                "VALUES(:wid,'Test',:slug,:id)"
            ),
            {"wid": workspace_id, "slug": str(workspace_id), "id": user_id},
        )
        db.execute(
            text(
                "INSERT INTO edu.workspace_members(user_id,workspace_id,role) "
                "VALUES(:id,:wid,'owner')"
            ),
            {"id": user_id, "wid": workspace_id},
        )
    return user_id, workspace_id


def test_cleanup_dry_run_rollback_and_retry(database):
    from scripts.cleanup_legacy_account import cleanup

    user_id, _ = seed_discardable(database)
    with database.begin() as db:
        assert (
            cleanup(db, "https://retired.auth0.com/", "auth0|" + str(user_id), user_id)["status"]
            == "dry_run"
        )
        assert db.scalar(text("SELECT count(*) FROM edu.users WHERE id=:id"), {"id": user_id}) == 1
    with pytest.raises(RuntimeError):
        with database.begin() as db:
            cleanup(db, "https://retired.auth0.com/", "auth0|" + str(user_id), user_id, True)
            raise RuntimeError("simulated failure")
    with database.begin() as db:
        assert db.scalar(text("SELECT count(*) FROM edu.users WHERE id=:id"), {"id": user_id}) == 1
        assert (
            cleanup(db, "https://retired.auth0.com/", "auth0|" + str(user_id), user_id, True)[
                "status"
            ]
            == "deleted"
        )
        assert (
            cleanup(db, "https://retired.auth0.com/", "auth0|" + str(user_id), user_id, True)[
                "status"
            ]
            == "already_absent"
        )


def test_cleanup_refuses_mismatched_and_linked_identity(database):
    from scripts.cleanup_legacy_account import cleanup

    user_id, _ = seed_discardable(database)
    with database.begin() as db:
        with pytest.raises(ValueError, match="do not match"):
            cleanup(db, "https://wrong.auth0.com/", "auth0|" + str(user_id), user_id, True)
        db.execute(
            text(
                "INSERT INTO edu.user_identities(issuer,subject,user_id) "
                "VALUES('https://better.example/','new',:id)"
            ),
            {"id": user_id},
        )
        with pytest.raises(ValueError, match="Additional identity"):
            cleanup(db, "https://retired.auth0.com/", "auth0|" + str(user_id), user_id, True)


def test_cleanup_refuses_shared_workspace(database):
    from scripts.cleanup_legacy_account import cleanup

    user_id, workspace_id = seed_discardable(database)
    other_id, _ = seed_discardable_other(database)
    with database.begin() as db:
        db.execute(
            text(
                "INSERT INTO edu.workspace_members(user_id,workspace_id,role) "
                "VALUES(:id,:wid,'teacher')"
            ),
            {"id": other_id, "wid": workspace_id},
        )
        with pytest.raises(ValueError, match="Shared workspace"):
            cleanup(db, "https://retired.auth0.com/", "auth0|" + str(user_id), user_id, True)


def seed_discardable_other(database):
    other_id = uuid4()
    with database.begin() as db:
        db.execute(
            text(
                "INSERT INTO edu.users(id,provider_issuer,provider_sub,email) "
                "VALUES(:id,'https://other.example/',:sub,'other@example.test')"
            ),
            {"id": other_id, "sub": str(other_id)},
        )
    return other_id, None


async def test_bootstrap_requires_the_current_agreements(api, database):
    client, headers, app = api
    subject = "terms-" + str(uuid4())
    refused = await client.post("/v1/auth/bootstrap", headers=headers(subject))
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "agreement_required"
    status = (await client.get("/v1/auth/agreements", headers=headers(subject))).json()
    assert status["upToDate"] is False and status["accepted"]["userAgreement"] is None
    outdated = await client.post(
        "/v1/auth/agreements",
        headers=headers(subject),
        json={"userAgreementVersion": "old", "privacyVersion": "old", "accepted": True},
    )
    assert outdated.status_code == 409
    assert outdated.json()["error"]["code"] == "agreement_version_outdated"
    first = await accept_agreements(client, headers(subject))
    again = await accept_agreements(client, headers(subject))  # idempotent replay
    assert first == again
    assert (await client.post("/v1/auth/bootstrap", headers=headers(subject))).status_code == 200
    with database.connect() as db:
        rows = db.execute(
            text(
                "SELECT a.document, a.version, a.method, a.client_hash FROM edu.user_agreements a "
                "JOIN edu.users u ON u.id = a.user_id WHERE u.provider_sub = :sub"
            ),
            {"sub": subject},
        ).all()
    assert sorted(r.document for r in rows) == ["privacy_notice", "user_agreement"]
    assert {r.method for r in rows} == {"signup"} and all(r.client_hash is None for r in rows)
    # A new version requires re-acceptance, recorded as "reaccept".
    previous = app.state.settings
    app.state.settings = previous.model_copy(update={"terms_version": "2026-11-v1"})
    try:
        gated = await client.post("/v1/auth/bootstrap", headers=headers(subject))
        assert gated.status_code == 409
        await accept_agreements(client, headers(subject))
        assert (
            await client.post("/v1/auth/bootstrap", headers=headers(subject))
        ).status_code == 200
    finally:
        app.state.settings = previous
    with database.connect() as db:
        methods = db.execute(
            text(
                "SELECT a.version, a.method FROM edu.user_agreements a JOIN edu.users u "
                "ON u.id = a.user_id WHERE u.provider_sub = :sub AND a.document = 'user_agreement'"
            ),
            {"sub": subject},
        ).all()
    assert ("2026-11-v1", "reaccept") in {(r.version, r.method) for r in methods}


async def test_runtime_sees_only_its_own_agreements_and_cannot_rewrite_them(api, database):
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import create_async_engine

    client, headers, app = api
    a, b = "ra-" + str(uuid4()), "rb-" + str(uuid4())
    await accept_agreements(client, headers(a))
    await accept_agreements(client, headers(b))
    engine = create_async_engine(app.state.settings.database_url.get_secret_value())
    try:
        async with engine.connect() as db:
            await db.execute(
                text(
                    "SELECT set_config('edu.issuer', :iss, false), "
                    "set_config('edu.subject', :sub, false)"
                ),
                {"iss": app.state.settings.auth_issuer, "sub": a},
            )
            visible = (
                await db.execute(text("SELECT DISTINCT user_id FROM edu.user_agreements"))
            ).all()
            assert len(visible) == 1
            for statement in (
                "UPDATE edu.user_agreements SET version = 'x'",
                "DELETE FROM edu.user_agreements",
            ):
                with pytest.raises(DBAPIError):
                    async with db.begin_nested():
                        await db.execute(text(statement))
    finally:
        await engine.dispose()
