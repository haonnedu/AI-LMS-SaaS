"""Privacy API with a fake session: auth, isolation, consent gate on attempt start, staff
consents and links, export/erasure requests, student self-service and the public link."""

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.api import consent_links as public_api
from app.api import privacy as teacher_api
from app.api import student as student_api
from app.api import student_privacy as student_privacy_api
from app.api.dependencies import get_session
from app.core.auth import CLAIM_NAMESPACE, TokenError
from app.core.config import Settings
from app.main import create_app
from app.models.privacy import StudentConsent
from app.services import privacy as service

NOW = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)
AUTH = {"Authorization": "Bearer good"}
TOKEN = "t" * 43
CONTACT = "0912 345 678"


class FakeVerifier:
    def verify_token(self, token):
        if token == "bad":
            raise TokenError("bad")
        return {
            "iss": "https://identity.example/",
            "sub": "user-1",
            CLAIM_NAMESPACE + "email": "u@example.com",
            CLAIM_NAMESPACE + "email_verified": True,
        }


class FakeResult(list):
    def first(self):
        return self[0] if self else None

    def one(self):
        return self[0]

    def all(self):
        return list(self)


def db_error(sqlstate):
    class Orig(Exception):
        pass

    orig = Orig("hidden")
    orig.sqlstate = sqlstate
    return DBAPIError("SELECT 1", {}, orig)


class FakeSession:
    def __init__(self):
        self.user = SimpleNamespace(id=uuid4(), is_active=True)
        self.workspace_rows = []
        self.scalar_queue = []
        self.execute_queue = []
        self.functions = {}
        self.statements = []
        self.added = []
        self.gets = {}

    @asynccontextmanager
    async def _transaction(self):
        yield

    def begin(self):
        return self._transaction()

    def begin_nested(self):
        return self._transaction()

    async def execute(self, statement, params=None):
        self.statements.append((statement, params))
        sql = str(statement)
        if "set_config" in sql:
            return FakeResult()
        for name, handler in self.functions.items():
            if name in sql:
                outcome = handler(params)
                if isinstance(outcome, Exception):
                    raise outcome
                return FakeResult(outcome)
        if "workspace_members" in sql and "SELECT edu.workspaces" in sql:
            return FakeResult(self.workspace_rows)
        return FakeResult(self.execute_queue.pop(0) if self.execute_queue else [])

    async def scalar(self, statement, params=None):
        self.statements.append((statement, params))
        if "edu.users" in str(statement) and "provider_sub" in str(statement):
            return self.user
        return self.scalar_queue.pop(0) if self.scalar_queue else None

    async def scalars(self, statement, params=None):
        self.statements.append((statement, params))
        return FakeResult(self.scalar_queue.pop(0) if self.scalar_queue else [])

    async def get(self, model, key):
        return self.gets.get(key)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def refresh(self, obj):
        # The database would load server-side timestamps (clock_timestamp()).
        for name, value in vars(obj).items():
            if hasattr(value, "compile"):
                setattr(obj, name, NOW)

    def bound_values(self):
        """Every literal sent with a statement (compiled ORM statements + text params)."""
        values = []
        for statement, params in self.statements:
            values.extend((params or {}).values())
            try:
                values.extend(statement.compile().params.values())
            except Exception:
                pass
        return values


class FakeStore:
    def presign_get(self, key, *, file_name, mime, ttl_seconds):
        assert ttl_seconds <= 300 and mime == "application/json"
        return "https://storage.example/signed", NOW + timedelta(seconds=ttl_seconds)


@pytest.fixture
def fake(monkeypatch):
    # Most tests exercise the optional guardian flow; signup-mode tests switch the setting.
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            privacy_consent_age=15,
            privacy_consent_mode="guardian",
        )
    )
    paths = {getattr(r, "path", "") for r in app.routes}
    for router in (teacher_api.router, student_privacy_api.router, public_api.router):
        if not any(route.path in paths for route in router.routes):
            app.include_router(router)
    if "/v1/student/assignments" not in paths:
        app.include_router(student_api.router)
    app.state.token_verifier = FakeVerifier()
    app.state.object_store = FakeStore()
    dispatched = []

    async def dispatch(job):
        dispatched.append(job)
        return True

    app.state.job_dispatcher = dispatch
    session = FakeSession()
    app.dependency_overrides[get_session] = lambda: session
    public_api.token_limiter.reset()
    public_api.global_limiter.reset()
    yield TestClient(app), session, dispatched
    public_api.token_limiter.reset()
    public_api.global_limiter.reset()


def member(session, role="owner"):
    workspace = SimpleNamespace(
        id=uuid4(), name="W", workspace_type="personal", personal_owner_user_id=session.user.id
    )
    session.workspace_rows = [(workspace, role)]
    return workspace


def student_row(workspace_id, **overrides):
    values = {
        "id": uuid4(),
        "workspace_id": workspace_id,
        "user_id": uuid4(),
        "display_name": "Nguyễn Văn An",
        "status": "active",
        "birth_year": 2013,
        "consent_status": "pending",
        "erased_at": None,
        "updated_at": NOW,
    }
    return SimpleNamespace(**(values | overrides))


def consent_row(workspace_id, student_id, method="paper_school", revoked_at=None):
    return SimpleNamespace(
        id=uuid4(),
        workspace_id=workspace_id,
        student_id=student_id,
        method=method,
        policy_version="2026-10-draft",
        granted_at=NOW,
        revoked_at=revoked_at,
    )


def request_row(workspace_id, *, kind="export", student_id=None, user_id=None, **overrides):
    values = {
        "id": uuid4(),
        "workspace_id": workspace_id,
        "kind": kind,
        "status": "queued",
        "student_id": student_id,
        "user_id": user_id,
        "background_job_id": uuid4(),
        "object_key": None,
        "created_at": NOW,
        "finished_at": None,
        "note": None,
    }
    return SimpleNamespace(**(values | overrides))


# ---- Authentication and isolation -----------------------------------------------------------


def test_every_authenticated_route_requires_a_token(fake):
    client, _, _ = fake
    ws, s, c = uuid4(), uuid4(), uuid4()
    calls = [
        ("get", f"/v1/workspaces/{ws}/classes/{c}/consents", None),
        ("post", f"/v1/workspaces/{ws}/students/{s}/consents", {"method": "paper_school"}),
        ("post", f"/v1/workspaces/{ws}/students/{s}/consents/{c}/revoke", {"reason": "x"}),
        ("post", f"/v1/workspaces/{ws}/students/{s}/consent-links", None),
        ("post", f"/v1/workspaces/{ws}/students/{s}/privacy-requests", {"kind": "export"}),
        ("post", f"/v1/workspaces/{ws}/students/{s}/erase", None),
        ("get", f"/v1/workspaces/{ws}/privacy-requests/{c}", None),
        ("put", "/v1/student/me/birth-year", {"birthYear": 2012}),
        ("get", "/v1/student/me/consent-status", None),
        ("post", "/v1/student/me/privacy-requests", {"kind": "export"}),
        ("get", f"/v1/student/me/privacy-requests/{c}", None),
    ]
    for method, path, body in calls:
        for headers in ({}, {"Authorization": "Bearer bad"}):
            kwargs = {"headers": headers} | ({"json": body} if body is not None else {})
            response = client.request(method.upper(), path, **kwargs)
            assert response.status_code == 401, (method, path)
            assert set(response.json()) == {"error", "requestId"}


def test_cross_workspace_teacher_routes_are_404(fake):
    client, session, _ = fake
    session.workspace_rows = []
    ws, s = uuid4(), uuid4()
    for method, suffix, body in [
        ("get", f"/classes/{uuid4()}/consents", None),
        ("post", f"/students/{s}/consents", {"method": "paper_school"}),
        ("post", f"/students/{s}/consent-links", None),
        ("post", f"/students/{s}/privacy-requests", {"kind": "export"}),
        ("post", f"/students/{s}/erase", None),
        ("get", f"/privacy-requests/{uuid4()}", None),
    ]:
        kwargs = {"headers": AUTH} | ({"json": body} if body is not None else {})
        response = client.request(method.upper(), f"/v1/workspaces/{ws}{suffix}", **kwargs)
        assert response.status_code == 404, suffix
        assert response.json()["error"]["code"] == "workspace_not_found"


def test_student_role_and_invisible_student(fake):
    client, session, _ = fake
    ws = member(session, "student")
    response = client.post(f"/v1/workspaces/{ws.id}/students/{uuid4()}/consent-links", headers=AUTH)
    assert response.status_code == 403
    ws = member(session, "teacher")
    session.execute_queue = [[]]  # not enrolled in a class this teacher teaches
    response = client.post(
        f"/v1/workspaces/{ws.id}/students/{uuid4()}/consents",
        json={"method": "paper_school"},
        headers=AUTH,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "student_not_found"


# ---- Consent gate on attempt start ----------------------------------------------------------


def test_start_attempt_maps_ev017_to_consent_required(fake):
    client, session, _ = fake
    seen = []
    session.functions["edu.student_start_attempt"] = lambda p: seen.append(p) or db_error("EV017")
    response = client.post(
        f"/v1/student/assignments/{uuid4()}/attempts", headers=AUTH | {"Idempotency-Key": "k"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "consent_required"
    assert seen[0]["consent_age"] == 15  # the configured age, 4-argument function
    sql = str(next(s for s, _ in session.statements if "student_start_attempt" in str(s)))
    assert ":consent_age" in sql


# ---- Staff consents, links, roster ----------------------------------------------------------


def test_staff_records_paper_consent_with_hashed_contact(fake, caplog):
    client, session, _ = fake
    ws = member(session)
    student = student_row(ws.id)
    session.execute_queue = [[student]]
    created = consent_row(ws.id, student.id)
    session.scalar_queue = [created]
    with caplog.at_level(logging.INFO):
        response = client.post(
            f"/v1/workspaces/{ws.id}/students/{student.id}/consents",
            json={
                "method": "paper_school",
                "guardianName": "Trần Thị Bình",
                "guardianContact": CONTACT,
                "evidenceNote": "Phiếu số 12",
            },
            headers=AUTH,
        )
    assert response.status_code == 201, response.text
    assert response.json() == {
        "id": str(created.id),
        "method": "paper_school",
        "policyVersion": "2026-10-draft",
        "grantedAt": NOW.isoformat().replace("+00:00", "Z"),
        "revokedAt": None,
    }
    values = session.bound_values()
    assert service.hash_contact(CONTACT) in values
    assert not any(isinstance(v, str) and "345" in v for v in values)
    assert "345" not in caplog.text and "Bình" not in caplog.text


def test_guardian_link_method_is_not_staff_recordable(fake):
    client, session, _ = fake
    ws = member(session)
    response = client.post(
        f"/v1/workspaces/{ws.id}/students/{uuid4()}/consents",
        json={"method": "guardian_link"},
        headers=AUTH,
    )
    assert response.status_code == 422


def test_self_adult_consent_requires_age(fake):
    client, session, _ = fake
    ws = member(session)
    student = student_row(ws.id, birth_year=2013)
    session.execute_queue = [[student]]
    response = client.post(
        f"/v1/workspaces/{ws.id}/students/{student.id}/consents",
        json={"method": "self_adult"},
        headers=AUTH,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "student_under_age"


def test_erased_student_cannot_get_a_consent(fake):
    client, session, _ = fake
    ws = member(session)
    student = student_row(ws.id, erased_at=NOW)
    session.execute_queue = [[student]]
    response = client.post(
        f"/v1/workspaces/{ws.id}/students/{student.id}/consents",
        json={"method": "paper_school"},
        headers=AUTH,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "student_erased"


def test_revoke_consent(fake):
    client, session, _ = fake
    ws = member(session)
    student = student_row(ws.id, consent_status="granted")
    consent = consent_row(ws.id, student.id)
    session.execute_queue = [[student]]
    session.scalar_queue = [consent]
    response = client.post(
        f"/v1/workspaces/{ws.id}/students/{student.id}/consents/{consent.id}/revoke",
        json={"reason": "Phụ huynh rút lại"},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert consent.revoke_reason == "Phụ huynh rút lại"
    session.execute_queue = [[student]]
    session.scalar_queue = [None]
    response = client.post(
        f"/v1/workspaces/{ws.id}/students/{student.id}/consents/{uuid4()}/revoke",
        json={"reason": "x"},
        headers=AUTH,
    )
    assert response.status_code == 404


def test_consent_link_token_is_returned_once(fake):
    client, session, _ = fake
    ws = member(session)
    student = student_row(ws.id)
    session.execute_queue = [[student]]
    link = SimpleNamespace(id=uuid4(), expires_at=NOW + timedelta(days=14))
    session.scalar_queue = [link]
    response = client.post(
        f"/v1/workspaces/{ws.id}/students/{student.id}/consent-links", headers=AUTH
    )
    assert response.status_code == 201
    token = response.json()["token"]
    assert service.is_plausible_token(token)
    assert set(response.json()) == {"id", "token", "expiresAt"}
    values = session.bound_values()
    assert service.hash_link_token(token) in values and token not in values


def test_class_consent_roster(fake):
    client, session, _ = fake
    ws = member(session)
    school_class = SimpleNamespace(id=uuid4(), workspace_id=ws.id, status="active")
    a = student_row(ws.id, display_name="An", consent_status="granted")
    b = student_row(ws.id, display_name="Bình", consent_status="pending", birth_year=None)
    c = student_row(ws.id, display_name="Chi", consent_status="unknown", birth_year=2000)
    session.scalar_queue = [school_class, [consent_row(ws.id, a.id)]]
    session.execute_queue = [[a, b, c]]
    response = client.get(
        f"/v1/workspaces/{ws.id}/classes/{school_class.id}/consents", headers=AUTH
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["consentAge"] == 15 and body["policyVersion"] == "2026-10-draft"
    assert body["mode"] == "guardian"
    assert body["summary"] == {
        "granted": 1,
        "pending": 1,
        "notRequired": 0,
        "revoked": 0,
        "unknown": 1,
    }
    rows = {item["displayName"]: item for item in body["items"]}
    assert rows["An"]["consentRequired"] is False and len(rows["An"]["consents"]) == 1
    assert rows["Bình"]["consentRequired"] is True
    assert rows["Chi"]["consentRequired"] is False  # adult by birth year
    assert "guardianName" not in response.text and "Hash" not in response.text


# ---- Export / erasure requests --------------------------------------------------------------


def test_teacher_export_request_is_accepted_and_dispatched(fake):
    client, session, dispatched = fake
    ws = member(session, "teacher")
    student = student_row(ws.id)
    session.execute_queue = [[student]]
    created = request_row(ws.id, student_id=student.id)
    session.scalar_queue = [None, created]  # no job for the key yet, then the request row
    response = client.post(
        f"/v1/workspaces/{ws.id}/students/{student.id}/privacy-requests",
        json={"kind": "export"},
        headers=AUTH,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["request"]["kind"] == "export" and body["request"]["status"] == "queued"
    assert body["job"]["kind"] == "privacy.export"
    assert len(dispatched) == 1 and dispatched[0].kind == "privacy.export"
    assert dispatched[0].input["studentId"] == str(student.id)


def test_erasure_needs_a_manager(fake):
    client, session, dispatched = fake
    ws = member(session, "teacher")
    response = client.post(f"/v1/workspaces/{ws.id}/students/{uuid4()}/erase", headers=AUTH)
    assert response.status_code == 403
    assert not dispatched


def test_erase_shortcut_creates_an_erasure(fake):
    client, session, dispatched = fake
    ws = member(session, "owner")
    student = student_row(ws.id)
    session.execute_queue = [[student]]
    created = request_row(ws.id, kind="erasure", student_id=student.id)
    session.scalar_queue = [None, None, created]  # no pending erasure, no job, request row
    response = client.post(f"/v1/workspaces/{ws.id}/students/{student.id}/erase", headers=AUTH)
    assert response.status_code == 202, response.text
    assert response.json()["job"]["kind"] == "privacy.erase"
    assert dispatched[0].kind == "privacy.erase"


def test_pending_erasure_is_returned_not_duplicated(fake):
    client, session, dispatched = fake
    ws = member(session, "admin")
    student = student_row(ws.id)
    session.execute_queue = [[student]]
    pending = request_row(ws.id, kind="erasure", student_id=student.id)
    session.scalar_queue = [pending]
    response = client.post(f"/v1/workspaces/{ws.id}/students/{student.id}/erase", headers=AUTH)
    assert response.status_code == 202
    assert response.json()["request"]["id"] == str(pending.id)
    assert response.json()["job"] is None and not dispatched


def test_finished_export_has_a_short_lived_download(fake):
    client, session, _ = fake
    ws = member(session, "owner")
    done = request_row(
        ws.id,
        student_id=uuid4(),
        status="succeeded",
        finished_at=NOW,
        object_key=f"ws/{ws.id}/privacy/x.json",
    )
    session.scalar_queue = [done]
    response = client.get(f"/v1/workspaces/{ws.id}/privacy-requests/{done.id}", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["downloadUrl"] == "https://storage.example/signed"
    assert body["status"] == "succeeded" and "objectKey" not in body
    session.scalar_queue = [None]
    missing = client.get(f"/v1/workspaces/{ws.id}/privacy-requests/{uuid4()}", headers=AUTH)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "privacy_request_not_found"


# ---- Student self-service -------------------------------------------------------------------


def state_row(ws_id, status="pending", required=True):
    return SimpleNamespace(
        out_workspace_id=ws_id,
        out_workspace_name="Trường A",
        out_student_id=uuid4(),
        out_class_name="10A1",
        out_birth_year=2013,
        out_consent_status=status,
        out_consent_required=required,
    )


def test_student_sets_birth_year_and_reads_status(fake):
    client, session, _ = fake
    ws_id = uuid4()
    seen = []
    session.functions["edu.student_set_birth_year"] = lambda p: (
        seen.append(p)
        or [
            SimpleNamespace(
                out_workspace_id=ws_id,
                out_student_id=uuid4(),
                out_consent_status="pending",
                out_consent_required=True,
            )
        ]
    )
    session.functions["edu.student_consent_status"] = lambda p: [state_row(ws_id)]
    response = client.put("/v1/student/me/birth-year", json={"birthYear": 2013}, headers=AUTH)
    assert response.status_code == 200, response.text
    assert seen == [{"year": 2013, "age": 15}]
    item = response.json()["items"][0]
    assert item == {
        "workspaceId": str(ws_id),
        "workspaceName": "Trường A",
        "className": "10A1",
        "birthYear": 2013,
        "consentStatus": "pending",
        "consentRequired": True,
        "policyVersion": "2026-10-draft",
    }
    status = client.get("/v1/student/me/consent-status", headers=AUTH)
    assert status.status_code == 200 and status.json()["consentAge"] == 15
    assert status.json()["mode"] == "guardian"


@pytest.mark.parametrize(
    "outcome,status,code",
    [
        (db_error("EV019"), 409, "birth_year_locked"),
        (db_error("22023"), 422, "invalid_birth_year"),
        (db_error("28000"), 403, "account_disabled"),
    ],
)
def test_birth_year_errors(fake, outcome, status, code):
    client, session, _ = fake
    session.functions["edu.student_set_birth_year"] = lambda p: outcome
    response = client.put("/v1/student/me/birth-year", json={"birthYear": 2013}, headers=AUTH)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_future_birth_year_is_rejected_before_the_database(fake):
    client, session, _ = fake
    response = client.put(
        "/v1/student/me/birth-year", json={"birthYear": NOW.year + 2}, headers=AUTH
    )
    assert response.status_code == 422
    assert not any("student_set_birth_year" in str(s) for s, _ in session.statements)


def test_student_self_requests_live_in_the_personal_workspace(fake):
    client, session, dispatched = fake
    ws = member(session, "owner")
    created = request_row(ws.id, user_id=session.user.id)
    session.scalar_queue = [None, created]
    response = client.post("/v1/student/me/privacy-requests", json={"kind": "export"}, headers=AUTH)
    assert response.status_code == 202, response.text
    job = dispatched[0]
    assert job.kind == "privacy.export" and job.workspace_id == ws.id
    assert job.input["userId"] == str(session.user.id) and "studentId" not in job.input

    done = request_row(
        ws.id,
        user_id=session.user.id,
        status="succeeded",
        finished_at=NOW,
        object_key=f"users/{session.user.id}/privacy/x.json",
    )
    session.scalar_queue = [done]
    fetched = client.get(f"/v1/student/me/privacy-requests/{done.id}", headers=AUTH)
    assert fetched.status_code == 200
    assert fetched.json()["downloadUrl"] == "https://storage.example/signed"


def test_student_without_personal_workspace(fake):
    client, session, _ = fake
    session.workspace_rows = []
    response = client.post(
        "/v1/student/me/privacy-requests", json={"kind": "erasure"}, headers=AUTH
    )
    assert response.status_code == 409


# ---- Public guardian link -------------------------------------------------------------------


def test_public_link_info(fake):
    client, session, _ = fake
    session.functions["edu.consent_link_info"] = lambda p: [("An", "Trường A", NOW)]
    response = client.get(f"/v1/public/consent-links/{TOKEN}")
    assert response.status_code == 200
    assert response.json() == {
        "studentDisplayName": "An",
        "workspaceName": "Trường A",
        "policyVersion": "2026-10-draft",
        "expiresAt": NOW.isoformat().replace("+00:00", "Z"),
    }


@pytest.mark.parametrize("state,status", [("P0002", 404), ("EV018", 410)])
def test_public_link_errors(fake, state, status):
    client, session, _ = fake
    session.functions["edu.consent_link_info"] = lambda p: db_error(state)
    session.functions["edu.guardian_consent_by_link"] = lambda p: db_error(state)
    assert client.get(f"/v1/public/consent-links/{TOKEN}").status_code == status
    response = client.post(
        f"/v1/public/consent-links/{TOKEN}",
        json={"guardianName": "Bình", "guardianContact": CONTACT, "agree": True},
    )
    assert response.status_code == status


def test_malformed_token_is_404_without_a_query(fake):
    client, session, _ = fake
    assert client.get("/v1/public/consent-links/short").status_code == 404
    assert not session.statements


def test_guardian_consent_hashes_the_contact(fake, caplog):
    client, session, _ = fake
    seen = []
    ids = (uuid4(), uuid4(), uuid4())
    session.functions["edu.guardian_consent_by_link"] = lambda p: seen.append(p) or [ids]
    with caplog.at_level(logging.INFO):
        response = client.post(
            f"/v1/public/consent-links/{TOKEN}",
            json={"guardianName": " Trần Thị Bình ", "guardianContact": CONTACT, "agree": True},
        )
    assert response.status_code == 200 and response.json() == {"status": "granted"}
    params = seen[0]
    assert params["contact"] == service.hash_contact(CONTACT)
    assert params["token_hash"] == service.hash_link_token(TOKEN)
    assert params["name"] == "Trần Thị Bình" and params["version"] == "2026-10-draft"
    ours = " ".join(
        f"{r.getMessage()} {vars(r)}" for r in caplog.records if r.name.startswith("eduvia")
    )
    assert "345" not in ours and TOKEN not in ours and "Bình" not in ours


def test_guardian_must_agree_and_give_valid_contact(fake):
    client, session, _ = fake
    session.functions["edu.guardian_consent_by_link"] = lambda p: [(uuid4(), uuid4(), uuid4())]
    url = f"/v1/public/consent-links/{TOKEN}"
    body = {"guardianName": "Bình", "guardianContact": CONTACT}
    assert client.post(url, json=body | {"agree": False}).status_code == 422
    assert client.post(url, json=body).status_code == 422
    bad = client.post(url, json=body | {"guardianContact": "abc", "agree": True})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "invalid_guardian_contact"


def test_public_link_is_rate_limited(fake):
    client, session, _ = fake
    session.functions["edu.consent_link_info"] = lambda p: db_error("P0002")
    codes = [client.get(f"/v1/public/consent-links/{TOKEN}").status_code for _ in range(12)]
    assert codes[:10] == [404] * 10
    assert codes[-1] == 429
    response = client.get(f"/v1/public/consent-links/{TOKEN}")
    assert response.json()["error"]["code"] == "rate_limited"


def test_consent_rows_have_no_plaintext_contact_column():
    columns = {c.name for c in StudentConsent.__table__.columns}
    assert "guardian_contact_hash" in columns
    assert not {"guardian_contact", "guardian_email", "guardian_phone"} & columns


# ---- Signup mode (decision 0009): guardian consent off -------------------------------------


def signup_mode(client):
    settings = client.app.state.settings
    client.app.state.settings = settings.model_copy(update={"privacy_consent_mode": "signup"})


def test_signup_mode_start_attempt_sends_the_sentinel_age(fake):
    client, session, _ = fake
    signup_mode(client)
    seen = []
    started = SimpleNamespace(
        out_attempt_id=uuid4(),
        out_created=True,
        out_status="in_progress",
        out_attempt_no=1,
        out_started_at=NOW,
        out_deadline_at=None,
        out_server_now=NOW,
    )
    session.functions["edu.student_start_attempt"] = lambda p: seen.append(p) or [started]
    response = client.post(
        f"/v1/student/assignments/{uuid4()}/attempts", headers=AUTH | {"Idempotency-Key": "k"}
    )
    assert response.status_code == 201, response.text
    assert seen[0]["consent_age"] == 0  # "consent not required" sentinel, 4-argument function


def test_signup_mode_consent_status_reports_the_mode(fake):
    client, session, _ = fake
    signup_mode(client)
    seen = []
    session.functions["edu.student_consent_status"] = lambda p: (
        seen.append(p) or [state_row(uuid4(), status="not_required", required=False)]
    )
    response = client.get("/v1/student/me/consent-status", headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "signup" and body["consentAge"] == 15
    assert seen == [{"age": 0}]
    assert body["items"][0]["consentRequired"] is False


def test_signup_mode_birth_year_uses_the_sentinel_age(fake):
    client, session, _ = fake
    signup_mode(client)
    seen = []
    session.functions["edu.student_set_birth_year"] = lambda p: seen.append(p) or []
    session.functions["edu.student_consent_status"] = lambda p: []
    response = client.put("/v1/student/me/birth-year", json={"birthYear": 2013}, headers=AUTH)
    assert response.status_code == 200, response.text
    assert seen == [{"year": 2013, "age": 0}]
    assert response.json() == {"consentAge": 15, "mode": "signup", "items": []}


def test_signup_mode_roster_still_works_and_requires_nothing(fake):
    client, session, _ = fake
    signup_mode(client)
    ws = member(session)
    school_class = SimpleNamespace(id=uuid4(), workspace_id=ws.id, status="active")
    a = student_row(ws.id, display_name="An", consent_status="pending", birth_year=None)
    b = student_row(ws.id, display_name="Bình", consent_status="unknown", birth_year=2013)
    session.scalar_queue = [school_class, []]
    session.execute_queue = [[a, b]]
    response = client.get(
        f"/v1/workspaces/{ws.id}/classes/{school_class.id}/consents", headers=AUTH
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "signup"
    assert [item["consentRequired"] for item in body["items"]] == [False, False]
    assert body["summary"]["pending"] == 1 and body["summary"]["unknown"] == 1
