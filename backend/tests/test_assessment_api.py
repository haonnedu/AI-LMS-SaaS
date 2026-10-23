"""Assessment API with a fake session: auth, isolation, DTO key-leak guards, overrides, results."""

import typing
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError

from app.api import assignments as teacher_api
from app.api import student as student_api
from app.api.dependencies import get_session
from app.core.auth import CLAIM_NAMESPACE, TokenError
from app.core.config import Settings
from app.main import create_app
from app.services import jobs as job_service

NOW = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)
AUTH = {"Authorization": "Bearer good"}
KEY_FIELDS = {"correctKey", "correct_key", "explanation", "answerKey", "key_explanation"}


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
    rowcount = 0

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
    """Membership rows for ``workspace_transaction``; queued answers for everything else."""

    def __init__(self):
        self.user = SimpleNamespace(id=uuid4(), is_active=True)
        self.workspace_rows = []
        self.scalar_queue = []
        self.execute_queue = []
        self.functions = {}
        self.statements = []

    @asynccontextmanager
    async def _transaction(self):
        yield

    def begin(self):
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
        return FakeResult(self.scalar_queue.pop(0) if self.scalar_queue else [])

    async def flush(self):
        pass


@pytest.fixture
def fake(monkeypatch):
    app = create_app(Settings(_env_file=None, environment="test"))
    paths = {getattr(r, "path", "") for r in app.routes}
    if "/v1/student/assignments" not in paths:
        app.include_router(student_api.router)  # main.py wiring is the orchestrator's change
    if "/v1/workspaces/{workspace_id}/assignments/{assignment_id}" not in paths:
        app.include_router(teacher_api.router)
    app.state.token_verifier = FakeVerifier()
    session = FakeSession()
    app.dependency_overrides[get_session] = lambda: session
    sent = []
    monkeypatch.setattr(job_service, "send_job", lambda *args, **kw: sent.append(args))
    yield TestClient(app), session, sent


def member(session, role="teacher"):
    workspace = SimpleNamespace(id=uuid4(), name="W", workspace_type="personal")
    session.workspace_rows = [(workspace, role)]
    return workspace


# ---- Authentication and tenant isolation ----------------------------------------------------


def test_every_route_requires_authentication(fake):
    client, _, _ = fake
    ws, a, t, i = uuid4(), uuid4(), uuid4(), uuid4()
    calls = [
        ("get", f"/v1/workspaces/{ws}/classes/{uuid4()}/assignments"),
        ("get", f"/v1/workspaces/{ws}/assignments/{a}/results"),
        ("post", f"/v1/workspaces/{ws}/assignments/{a}/publish"),
        ("post", f"/v1/workspaces/{ws}/assignments/{a}/attempts/{t}/override"),
        ("get", "/v1/student/assignments"),
        ("post", f"/v1/student/assignments/{a}/attempts"),
        ("get", f"/v1/student/attempts/{t}"),
        ("put", f"/v1/student/attempts/{t}/answers/{i}"),
        ("post", f"/v1/student/attempts/{t}/submit"),
        ("get", f"/v1/student/attempts/{t}/results"),
    ]
    for method, path in calls:
        for headers in ({}, {"Authorization": "Bearer bad"}):
            response = getattr(client, method)(path, headers=headers)
            assert response.status_code == 401, (method, path)
            assert set(response.json()) == {"error", "requestId"}


def test_cross_workspace_teacher_routes_are_404(fake):
    client, session, _ = fake
    session.workspace_rows = []  # not a member of the requested workspace
    for method, suffix in [
        ("get", f"/assignments/{uuid4()}"),
        ("get", f"/assignments/{uuid4()}/results"),
        ("get", f"/assignments/{uuid4()}/results/export.csv"),
        ("post", f"/assignments/{uuid4()}/release-scores"),
    ]:
        response = getattr(client, method)(f"/v1/workspaces/{uuid4()}{suffix}", headers=AUTH)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "workspace_not_found"


def test_invisible_assignment_is_404_and_student_role_is_403(fake):
    client, session, _ = fake
    ws = member(session)
    session.scalar_queue = [None]
    response = client.get(f"/v1/workspaces/{ws.id}/assignments/{uuid4()}", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "assignment_not_found"
    ws = member(session, "student")
    response = client.get(f"/v1/workspaces/{ws.id}/assignments/{uuid4()}/results", headers=AUTH)
    assert response.status_code == 403


# ---- DTO key-leak guards --------------------------------------------------------------------


def model_fields(model, seen=None):
    """All field names reachable from a pydantic model (nested models, lists, optionals)."""
    seen = seen if seen is not None else set()
    if model in seen:
        return set()
    seen.add(model)
    names = set(model.model_fields)
    for field in model.model_fields.values():
        stack = [field.annotation]
        while stack:
            annotation = stack.pop()
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                names |= model_fields(annotation, seen)
            stack.extend(typing.get_args(annotation))
    return names


@pytest.mark.parametrize("dto", student_api.PRE_RELEASE_DTOS, ids=lambda d: d.__name__)
def test_student_dtos_have_no_key_or_explanation_fields(dto):
    assert not model_fields(dto) & KEY_FIELDS


def test_every_student_route_response_is_guarded():
    guarded = set(student_api.PRE_RELEASE_DTOS) | {
        student_api.StudentAssignmentListDTO,
        student_api.StudentResultDTO,
    }
    for route in student_api.router.routes:
        assert route.response_model in guarded, route.path
    assert not model_fields(student_api.StudentAssignmentListDTO) & KEY_FIELDS
    # Results expose keys only inside the nullable, release-gated ``solution`` object.
    result_fields = set(student_api.StudentResultDTO.model_fields)
    item_fields = set(student_api.ResultItemDTO.model_fields)
    assert not (result_fields | item_fields) & KEY_FIELDS
    assert item_fields >= {"solution"}


def results_payload(**overrides):
    item = {
        "itemId": str(uuid4()),
        "position": 1,
        "selectedKey": "A",
        "maxPoints": "1.00",
        "awardedPoints": None,
        "solution": {"correctKey": "B", "explanation": "Vì..."},
    }
    return {
        "attemptId": str(uuid4()),
        "assignmentId": str(uuid4()),
        "status": "graded",
        "submittedAt": NOW.isoformat(),
        "gradingStatus": "graded",
        "scoreReleased": False,
        "score": "1.00",
        "maxScore": "2.00",
        "releasedAt": None,
        "solutionsReleased": False,
        "items": [item],
    } | overrides


def test_result_mapping_drops_unreleased_score_and_solution_defensively():
    dto = student_api.result_dto(results_payload())
    assert dto.score is None and dto.maxScore is None
    assert dto.items[0].solution is None
    released = student_api.result_dto(
        results_payload(scoreReleased=True, solutionsReleased=True, releasedAt=NOW.isoformat())
    )
    assert released.score == Decimal("1.00")
    assert released.items[0].solution.correctKey == "B"


def test_student_results_before_release_contain_no_key(fake):
    client, session, _ = fake
    payload = results_payload(
        gradingStatus="pending",
        status="submitted",
        score=None,
        maxScore=None,
        items=[
            {
                "itemId": str(uuid4()),
                "position": 1,
                "selectedKey": "A",
                "maxPoints": "1.00",
                "awardedPoints": None,
                "solution": None,
            }
        ],
    )
    session.functions["edu.student_results"] = lambda p: [SimpleNamespace(out_results=payload)]
    response = client.get(f"/v1/student/attempts/{uuid4()}/results", headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gradingStatus"] == "pending" and body["score"] is None
    assert "correctKey" not in response.text and "explanation" not in response.text


# ---- Student routes -------------------------------------------------------------------------


def started_row(created=True):
    return SimpleNamespace(
        out_attempt_id=uuid4(),
        out_created=created,
        out_status="in_progress",
        out_attempt_no=1,
        out_started_at=NOW,
        out_deadline_at=NOW + timedelta(minutes=15),
        out_server_now=NOW,
    )


def test_start_requires_idempotency_key_and_reports_creation(fake):
    client, session, _ = fake
    url = f"/v1/student/assignments/{uuid4()}/attempts"
    response = client.post(url, headers=AUTH)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "idempotency_key_required"
    seen = []
    rows = [started_row(True), started_row(False)]
    session.functions["edu.student_start_attempt"] = lambda p: seen.append(p) or [rows.pop(0)]
    first = client.post(url, headers=AUTH | {"Idempotency-Key": "abc-1"})
    again = client.post(url, headers=AUTH | {"Idempotency-Key": "abc-2"})
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["created"] is True and again.json()["created"] is False
    assert seen[0]["key"] == "client:abc-1"  # namespaced client key, server-derived hash
    assert seen[0]["hash"] == seen[1]["hash"]


@pytest.mark.parametrize(
    "state,status,code",
    [
        ("P0002", 404, "assignment_not_found"),
        ("EV012", 409, "assignment_unavailable"),
        ("EV013", 409, "attempt_limit_reached"),
        ("EV011", 409, "idempotency_conflict"),
        ("28000", 403, "account_disabled"),
        ("XX000", 503, "database_unavailable"),
    ],
)
def test_start_error_mapping(fake, state, status, code):
    client, session, _ = fake
    session.functions["edu.student_start_attempt"] = lambda p: db_error(state)
    response = client.post(
        f"/v1/student/assignments/{uuid4()}/attempts", headers=AUTH | {"Idempotency-Key": "k"}
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize(
    "body",
    [
        {"selectedKey": "AB", "expectedRevision": 0, "clientSequence": 1},
        {"selectedKey": "a", "expectedRevision": 0, "clientSequence": 1},
        {"selectedKey": "A", "expectedRevision": -1, "clientSequence": 1},
        {"selectedKey": "A", "expectedRevision": 0},
        {"selectedKey": "A", "expectedRevision": 0, "clientSequence": 1, "score": 10},
        {"selectedKey": "A", "expectedRevision": 0, "clientSequence": 1, "correct": True},
    ],
)
def test_answer_validation(fake, body):
    client, _, _ = fake
    response = client.put(
        f"/v1/student/attempts/{uuid4()}/answers/{uuid4()}", json=body, headers=AUTH
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "state,status,code",
    [
        ("EV014", 409, "stale_answer"),
        ("EV010", 409, "attempt_expired"),
        ("EV015", 409, "attempt_closed"),
        ("EV016", 422, "invalid_option"),
        ("P0002", 404, "attempt_not_found"),
    ],
)
def test_answer_conflicts(fake, state, status, code):
    client, session, _ = fake
    session.functions["edu.student_save_answer"] = lambda p: db_error(state)
    response = client.put(
        f"/v1/student/attempts/{uuid4()}/answers/{uuid4()}",
        json={"selectedKey": "A", "expectedRevision": 0, "clientSequence": 1},
        headers=AUTH,
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_answer_saved_returns_server_ack(fake):
    client, session, _ = fake
    seen = []
    session.functions["edu.student_save_answer"] = lambda p: (
        seen.append(p)
        or [SimpleNamespace(out_answer_revision=3, out_saved_at=NOW, out_server_now=NOW)]
    )
    response = client.put(
        f"/v1/student/attempts/{uuid4()}/answers/{uuid4()}",
        json={"selectedKey": None, "expectedRevision": 2, "clientSequence": 9},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json()["answerRevision"] == 3
    assert seen[0]["key"] is None and seen[0]["sequence"] == 9


def test_submit_dispatches_grading_once(fake):
    client, session, sent = fake
    job = uuid4()
    rows = [
        SimpleNamespace(
            out_status="submitted",
            out_submitted_at=NOW,
            out_snapshot_sha256=b"\x01" * 32,
            out_submission_reason="student",
            out_job_id=job,
            out_replayed=False,
        ),
        SimpleNamespace(
            out_status="submitted",
            out_submitted_at=NOW,
            out_snapshot_sha256=b"\x01" * 32,
            out_submission_reason="student",
            out_job_id=None,
            out_replayed=True,
        ),
    ]
    session.functions["edu.student_submit"] = lambda p: [rows.pop(0)]
    url = f"/v1/student/attempts/{uuid4()}/submit"
    assert client.post(url, headers=AUTH).status_code == 422
    first = client.post(url, headers=AUTH | {"Idempotency-Key": "s-1"})
    second = client.post(url, headers=AUTH | {"Idempotency-Key": "s-1"})
    assert first.status_code == second.status_code == 200
    assert first.json()["snapshotSha256"] == second.json()["snapshotSha256"] == "01" * 32
    assert second.json()["replayed"] is True
    assert sent == [(job, "attempt.grade")]


def test_attempt_view_hides_extra_choice_fields(fake):
    client, session, _ = fake
    attempt = uuid4()
    session.functions["edu.student_attempt_items"] = lambda p: [
        SimpleNamespace(
            out_item_id=uuid4(),
            out_position=1,
            out_stem="1 + 1 = ?",
            out_choices=[{"key": "A", "text": "2", "isCorrect": True}, {"key": "B", "text": "3"}],
            out_points=Decimal("1.00"),
            out_selected_key=None,
            out_answer_revision=0,
            out_client_sequence=0,
            out_saved_at=None,
        )
    ]
    session.functions["edu.student_attempt("] = lambda p: [
        SimpleNamespace(
            out_attempt_id=attempt,
            out_assignment_id=uuid4(),
            out_title="Kiểm tra",
            out_attempt_no=1,
            out_status="in_progress",
            out_started_at=NOW,
            out_deadline_at=None,
            out_submitted_at=None,
            out_submission_reason=None,
            out_snapshot_sha256=None,
            out_answer_sequence=0,
            out_server_now=NOW,
        )
    ]
    response = client.get(f"/v1/student/attempts/{attempt}", headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["choices"] == [
        {"key": "A", "text": "2"},
        {"key": "B", "text": "3"},
    ]
    assert "isCorrect" not in response.text


# ---- Teacher routes -------------------------------------------------------------------------


def teacher_assignment(ws, **overrides):
    values = {
        "id": uuid4(),
        "workspace_id": ws.id,
        "class_id": uuid4(),
        "exam_version_id": uuid4(),
        "title": "Kiểm tra 15 phút",
        "instructions": None,
        "opens_at": NOW,
        "closes_at": NOW + timedelta(hours=1),
        "time_limit_seconds": 900,
        "max_attempts": 1,
        "timezone": "Asia/Ho_Chi_Minh",
        "status": "published",
        "score_release": "manual",
        "solution_release": "manual",
        "scores_released_at": None,
        "solutions_released_at": None,
        "published_at": NOW,
        "created_at": NOW,
    } | overrides
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "body",
    [
        {"score": "1.00"},
        {"score": "1.00", "reason": ""},
        {"score": "1.00", "reason": "   "},
        {"score": "1.005", "reason": "Phúc khảo"},
        {"score": "-1", "reason": "Phúc khảo"},
        {"reason": "Phúc khảo"},
    ],
)
def test_override_requires_reason_and_valid_score(fake, body):
    client, session, _ = fake
    ws = member(session)
    response = client.post(
        f"/v1/workspaces/{ws.id}/assignments/{uuid4()}/attempts/{uuid4()}/override",
        json=body,
        headers=AUTH,
    )
    assert response.status_code == 422


def test_results_show_pending_not_zero(fake):
    client, session, _ = fake
    ws = member(session)
    assignment = teacher_assignment(ws)
    graded, pending, missing = uuid4(), uuid4(), uuid4()
    graded_attempt, pending_attempt = uuid4(), uuid4()
    session.scalar_queue = [assignment, SimpleNamespace(id=assignment.class_id, status="active")]
    session.execute_queue = [
        [(graded, "An"), (pending, "Bình"), (missing, "Chi")],
        [
            (graded_attempt, graded, 1, "graded", NOW),
            (pending_attempt, pending, 1, "submitted", NOW),
        ],
        [(graded_attempt, Decimal("8.50"), Decimal("10.00"))],
    ]
    response = client.get(
        f"/v1/workspaces/{ws.id}/assignments/{assignment.id}/results", headers=AUTH
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["denominators"] == {
        "enrolled": 3,
        "started": 2,
        "submitted": 2,
        "graded": 1,
        "pending": 1,
    }
    items = {item["displayName"]: item for item in body["items"]}
    assert items["An"]["score"] == "8.50" and items["An"]["gradingStatus"] == "graded"
    assert items["Bình"]["score"] is None and items["Bình"]["gradingStatus"] == "pending"
    assert items["Chi"]["status"] == "not_started" and items["Chi"]["score"] is None
    assert "correctKey" not in response.text


def test_results_export_is_csv_scores_only(fake):
    client, session, _ = fake
    ws = member(session)
    assignment = teacher_assignment(ws)
    session.scalar_queue = [assignment, SimpleNamespace(id=assignment.class_id, status="active")]
    session.execute_queue = [[(uuid4(), "An")], [], []]
    response = client.get(
        f"/v1/workspaces/{ws.id}/assignments/{assignment.id}/results/export.csv", headers=AUTH
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    assert "not_started" in response.text


def test_release_solutions_while_open_is_409(fake):
    client, session, _ = fake
    ws = member(session)
    assignment = teacher_assignment(ws, closes_at=datetime.now(UTC) + timedelta(hours=1))
    session.scalar_queue = [
        assignment,
        SimpleNamespace(id=assignment.class_id, status="active"),
        0,
    ]
    response = client.post(
        f"/v1/workspaces/{ws.id}/assignments/{assignment.id}/release-solutions", headers=AUTH
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "assignment_still_open"


def test_create_assignment_validation(fake):
    client, session, _ = fake
    ws = member(session)
    url = f"/v1/workspaces/{ws.id}/classes/{uuid4()}/assignments"
    base = {"examVersionId": str(uuid4()), "title": "Bài 1", "opensAt": NOW.isoformat()}
    for bad in (
        base | {"maxAttempts": 6},
        base | {"timeLimitSeconds": 30},
        base | {"scoreRelease": "never"},
        base | {"status": "published"},
        base | {"title": "  "},
    ):
        assert client.post(url, json=bad, headers=AUTH).status_code == 422
