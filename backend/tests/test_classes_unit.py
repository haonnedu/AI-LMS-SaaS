"""Classes/invitations without PostgreSQL: pure helpers, limiter, DTOs and endpoint guards."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from app.api import classes as api
from app.api.dependencies import get_session
from app.core.auth import CLAIM_NAMESPACE, TokenError
from app.core.config import Settings
from app.main import create_app
from app.services import classes as service

NOW = datetime(2026, 10, 23, tzinfo=UTC)


# ---- Pure helpers ---------------------------------------------------------------------------


def test_token_is_random_and_only_hash_is_derived():
    token, digest = service.new_invitation_token()
    other, other_digest = service.new_invitation_token()
    assert token != other and digest != other_digest
    assert len(token) == 43 and service.is_plausible_token(token)
    assert len(digest) == 32 and digest == service.hash_token(token)
    assert token.encode() not in digest


@pytest.mark.parametrize("token", ["", "short", "a" * 31, "a" * 129, "a" * 40 + "/", "é" * 40])
def test_implausible_tokens_rejected(token):
    assert not service.is_plausible_token(token)


@pytest.mark.parametrize("hours", [1, 168, 720])
def test_expiry_within_thirty_days(hours):
    assert service.invitation_expiry(NOW, hours) == NOW + timedelta(hours=hours)


@pytest.mark.parametrize("hours", [0, -1, 721])
def test_expiry_out_of_bounds(hours):
    with pytest.raises(ValueError):
        service.invitation_expiry(NOW, hours)


@pytest.mark.parametrize("uses,ok", [(0, False), (1, True), (500, True), (501, False)])
def test_max_uses_bounds(uses, ok):
    if ok:
        assert service.validate_max_uses(uses) == uses
    else:
        with pytest.raises(ValueError):
            service.validate_max_uses(uses)


@pytest.mark.parametrize(
    "revoked,expires_delta,used,max_uses,reason",
    [
        (None, 1, 0, 1, None),
        (NOW, 1, 0, 1, "revoked"),
        (NOW, -1, 1, 1, "revoked"),
        (None, 0, 0, 1, "expired"),
        (None, -1, 0, 5, "expired"),
        (None, 1, 1, 1, "exhausted"),
        (None, 1, 4, 5, None),
    ],
)
def test_invitation_state_mirrors_sql(revoked, expires_delta, used, max_uses, reason):
    assert (
        service.invitation_unavailable_reason(
            revoked_at=revoked,
            expires_at=NOW + timedelta(seconds=expires_delta),
            use_count=used,
            max_uses=max_uses,
            now=NOW,
        )
        == reason
    )


def test_pagination_cursor_math():
    rows = [SimpleNamespace(id=uuid4()) for _ in range(3)]
    items, cursor = service.page(rows, 2, lambda r: r.id)
    assert items == rows[:2] and cursor == rows[1].id
    items, cursor = service.page(rows[:2], 2, lambda r: r.id)
    assert items == rows[:2] and cursor is None
    assert service.page([], 5, lambda r: r.id) == ([], None)


def test_roster_counts():
    assert service.roster_counts(["active", "active", "withdrawn", "invited"]) == {
        "enrolled": 2,
        "invited": 1,
        "withdrawn": 1,
    }


# ---- Rate limiter ---------------------------------------------------------------------------


def test_token_bucket_refills_over_time():
    clock = [0.0]
    limiter = api.TokenBucketLimiter(capacity=2, refill_per_second=0.5, clock=lambda: clock[0])
    assert [limiter.allow("k") for _ in range(3)] == [True, True, False]
    assert limiter.allow("other")
    clock[0] += 1.0
    assert not limiter.allow("k")
    clock[0] += 1.0
    assert limiter.allow("k")
    assert not limiter.allow("k")


def test_token_bucket_memory_is_bounded():
    limiter = api.TokenBucketLimiter(capacity=1, refill_per_second=0, max_keys=2, clock=lambda: 0)
    assert limiter.allow("a") and limiter.allow("b") and limiter.allow("c")
    assert len(limiter._buckets) == 2 and "a" not in limiter._buckets


# ---- DTO validation -------------------------------------------------------------------------


def test_class_dto_strips_and_rejects():
    assert api.ClassCreateDTO(name="  10A1 ").name == "10A1"
    for bad in ({"name": "   "}, {"name": "x" * 201}, {"name": "A", "workspaceId": "x"}):
        with pytest.raises(ValidationError):
            api.ClassCreateDTO(**bad)


def test_invitation_dto_bounds():
    assert api.InvitationCreateDTO().model_dump() == {"expiresInHours": 168, "maxUses": 1}
    for bad in ({"maxUses": 0}, {"maxUses": 501}, {"expiresInHours": 721}, {"tokenHash": "x"}):
        with pytest.raises(ValidationError):
            api.InvitationCreateDTO(**bad)


def test_created_dto_never_carries_hash():
    assert "tokenHash" not in api.InvitationCreatedDTO.model_fields
    assert "tokenHash" not in api.InvitationDTO.model_fields


# ---- Endpoints with a fake session ----------------------------------------------------------


class FakeVerifier:
    def verify_token(self, token):
        if token == "bad":
            raise TokenError("bad")
        return {
            "iss": "https://identity.example/",
            "sub": "teacher-1",
            CLAIM_NAMESPACE + "email": "t@example.com",
            CLAIM_NAMESPACE + "email_verified": True,
        }


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def first(self):
        return self.rows[0] if self.rows else None

    def one(self):
        return self.rows[0]

    def all(self):
        return self.rows


class FakeSession:
    """Answers the membership query with ``workspace_rows`` and ``scalar`` from a queue."""

    def __init__(self):
        self.user = SimpleNamespace(id=uuid4(), is_active=True)
        self.workspace_rows = []
        self.scalars = []
        self.statements = []
        self.on_text = None

    @asynccontextmanager
    async def _transaction(self):
        yield

    def begin(self):
        return self._transaction()

    async def execute(self, statement, params=None):
        self.statements.append(statement)
        sql = str(statement)
        if "set_config" in sql:
            return FakeResult([])
        if "accept_class_invitation" in sql and self.on_text:
            return self.on_text(params)
        return FakeResult(self.workspace_rows)

    async def scalar(self, statement, params=None):
        self.statements.append(statement)
        if "edu.users" in str(statement) and "provider_sub" in str(statement):
            return self.user
        return self.scalars.pop(0) if self.scalars else None


@pytest.fixture
def fake():
    api.token_limiter.reset()
    api.actor_limiter.reset()
    app = create_app(Settings(_env_file=None, environment="test"))
    if not any(getattr(r, "path", "").endswith("/classes") for r in app.routes):
        app.include_router(api.router)  # main.py wiring is the orchestrator's change
    app.state.token_verifier = FakeVerifier()
    session = FakeSession()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    yield client, session
    api.token_limiter.reset()
    api.actor_limiter.reset()


AUTH = {"Authorization": "Bearer good"}


def member(session, role="teacher"):
    workspace = SimpleNamespace(id=uuid4(), name="W", workspace_type="personal")
    session.workspace_rows = [(workspace, role)]
    return workspace


def test_requires_authentication(fake):
    client, _ = fake
    url = f"/v1/workspaces/{uuid4()}/classes"
    for response in (
        client.get(url),
        client.post(url, json={"name": "10A1"}),
        client.post(url, json={"name": "10A1"}, headers={"Authorization": "Bearer bad"}),
        client.post("/v1/invitations/" + "a" * 43 + "/accept"),
    ):
        assert response.status_code == 401
        assert set(response.json()) == {"error", "requestId"}


def test_workspace_not_member_is_404(fake):
    client, session = fake
    session.workspace_rows = []
    response = client.get(f"/v1/workspaces/{uuid4()}/classes", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "workspace_not_found"


def test_student_role_cannot_manage_classes(fake):
    client, session = fake
    workspace = member(session, "student")
    response = client.post(
        f"/v1/workspaces/{workspace.id}/classes", json={"name": "10A1"}, headers=AUTH
    )
    assert response.status_code == 403


def test_invisible_class_is_404_not_403(fake):
    client, session = fake
    workspace = member(session)
    session.scalars = [None]
    response = client.get(f"/v1/workspaces/{workspace.id}/classes/{uuid4()}/roster", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "class_not_found"


@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("post", "/classes", {"name": "  "}),
        ("post", "/classes", {"name": "A", "status": "active"}),
        ("get", "/classes?limit=101", None),
        ("get", "/classes?status=deleted", None),
        ("post", f"/classes/{uuid4()}/invitations", {"maxUses": 501}),
        ("post", f"/classes/{uuid4()}/invitations", {"expiresInHours": 0}),
        ("post", f"/classes/{uuid4()}/teachers", {"userId": "nope"}),
        ("get", "/classes/not-a-uuid", None),
    ],
)
def test_validation_errors_use_envelope(fake, method, suffix, body):
    client, session = fake
    workspace = member(session)
    kwargs = {"headers": AUTH} | ({"json": body} if body is not None else {})
    response = getattr(client, method)(f"/v1/workspaces/{workspace.id}{suffix}", **kwargs)
    assert response.status_code == 422
    assert set(response.json()) == {"error", "requestId"}


def test_create_invitation_returns_token_once_and_stores_hash(fake):
    client, session = fake
    workspace = member(session)
    class_id = uuid4()
    invitation = SimpleNamespace(
        id=uuid4(), expires_at=NOW + timedelta(days=7), max_uses=3, class_id=class_id
    )
    session.scalars = [SimpleNamespace(id=class_id, status="active"), invitation]
    response = client.post(
        f"/v1/workspaces/{workspace.id}/classes/{class_id}/invitations",
        json={"maxUses": 3},
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"id", "token", "expiresAt", "maxUses"}
    assert response.headers["cache-control"] == "no-store"
    inserted = next(s for s in session.statements if "class_invitations" in str(s))
    params = inserted.compile().params
    assert params["token_hash"] == service.hash_token(body["token"])
    assert body["token"] not in str(params)


def test_archived_class_rejects_new_invitation(fake):
    client, session = fake
    workspace = member(session)
    session.scalars = [SimpleNamespace(id=uuid4(), status="archived")]
    response = client.post(
        f"/v1/workspaces/{workspace.id}/classes/{uuid4()}/invitations", headers=AUTH
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "class_archived"


def _db_error(sqlstate):
    class Orig(Exception):
        pass

    orig = Orig("hidden")
    orig.sqlstate = sqlstate
    return DBAPIError("SELECT 1", {}, orig)


@pytest.mark.parametrize(
    "sqlstate,status,code",
    [
        ("P0002", 404, "invitation_not_found"),
        ("EV001", 410, "invitation_unavailable"),
        ("EV002", 409, "enrollment_withdrawn"),
        ("XX000", 503, "database_unavailable"),
    ],
)
def test_accept_maps_database_outcomes(fake, sqlstate, status, code):
    client, session = fake

    def fail(params):
        raise _db_error(sqlstate)

    session.on_text = fail
    response = client.post("/v1/invitations/" + "a" * 43 + "/accept", headers=AUTH)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_accept_success_passes_only_hash(fake):
    client, session = fake
    token = "b" * 43
    ids = [uuid4(), uuid4(), uuid4()]
    seen = []

    def accept(params):
        seen.append(params)
        return FakeResult([(ids[0], ids[1], "10A1", ids[2])])

    session.on_text = accept
    response = client.post(f"/v1/invitations/{token}/accept", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {
        "classId": str(ids[1]),
        "className": "10A1",
        "workspaceId": str(ids[2]),
        "enrollmentId": str(ids[0]),
    }
    assert seen == [{"token_hash": service.hash_token(token)}]


def test_accept_rejects_malformed_token(fake):
    client, _ = fake
    assert client.post("/v1/invitations/short/accept", headers=AUTH).status_code == 422


def test_accept_is_rate_limited_per_actor_and_token_prefix(fake):
    client, session = fake
    session.on_text = lambda params: (_ for _ in ()).throw(_db_error("P0002"))
    token = "c" * 43
    codes = [
        client.post(f"/v1/invitations/{token}/accept", headers=AUTH).status_code
        for _ in range(api.actor_limiter.capacity + 1)
    ]
    assert codes[:-1] == [404] * int(api.actor_limiter.capacity)
    assert codes[-1] == 429
    other = client.post("/v1/invitations/" + "d" * 43 + "/accept", headers=AUTH)
    assert other.status_code == 404
