"""Authoring API with TestClient, a fake token verifier and the in-memory session, following
the harness in test_knowledge_api.py (main.py wiring of the router is done here)."""

import csv
import io
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from authoring_fakes import FakeSession
from fastapi.testclient import TestClient

from app.api import authoring as api
from app.api.dependencies import get_session
from app.api.identity import ApiError
from app.api.workspace_access import WorkspaceScope
from app.core.auth import CLAIM_NAMESPACE, TokenError
from app.core.config import Settings
from app.main import create_app
from app.models.knowledge import CurriculumSubject, CurriculumUnit
from app.services import question_bank as bank

GOOD = {"Authorization": "Bearer good"}
CSV_HEADERS = {**GOOD, "Content-Type": "text/csv; charset=utf-8"}


class FakeVerifier:
    def verify_token(self, token):
        if token != "good":
            raise TokenError("invalid")
        return {
            "iss": "https://identity.example/",
            "sub": "teacher-1",
            CLAIM_NAMESPACE + "email": "teacher@example.com",
            CLAIM_NAMESPACE + "email_verified": True,
        }


class Harness:
    def __init__(self, monkeypatch):
        self.workspace_id = uuid4()
        self.user = SimpleNamespace(id=uuid4())
        settings = Settings(
            _env_file=None,
            environment="test",
            database_url="postgresql+psycopg://eduvia_runtime:x@localhost/eduvia_test",
            auth_issuer="https://identity.example/",
            auth_audience="eduvia-api",
            auth_jwks_url="https://identity.example/jwks",
            s3_bucket="eduvia-test",
        )
        app = create_app(settings)
        paths = {getattr(route, "path", "") for route in app.routes}
        if not any(route.path in paths for route in api.router.routes):
            app.include_router(api.router)
        app.state.token_verifier = FakeVerifier()
        self.db = FakeSession()
        app.dependency_overrides[get_session] = lambda: self.db
        self.role = "owner"
        self.audits = []
        workspace = SimpleNamespace(id=self.workspace_id)

        @asynccontextmanager
        async def fake_transaction(db, claims, workspace_id, *, roles=None):
            assert db is self.db and claims["sub"] == "teacher-1"
            if workspace_id != self.workspace_id:
                raise ApiError(404, "workspace_not_found", "Workspace not found.")
            if roles is not None and self.role not in roles:
                raise ApiError(403, "forbidden", "You cannot perform this action here.")
            yield WorkspaceScope(user=self.user, workspace=workspace, role=self.role)

        monkeypatch.setattr(api, "workspace_transaction", fake_transaction)
        monkeypatch.setattr(
            api, "audit", lambda event, **fields: self.audits.append((event, fields))
        )
        self.client = TestClient(app, raise_server_exceptions=False)
        self.subject = CurriculumSubject(id=uuid4(), code="toan")
        self.unit = CurriculumUnit(
            id=uuid4(), subject_id=self.subject.id, grade=10, unit_code="T10-01"
        )
        self.db.add(self.subject)
        self.db.add(self.unit)

    def url(self, suffix="", workspace_id=None):
        return f"/v1/workspaces/{workspace_id or self.workspace_id}{suffix}"

    def post(self, suffix, json=None, **kwargs):
        return self.client.post(self.url(suffix), json=json, headers=GOOD, **kwargs)


@pytest.fixture
def harness(monkeypatch):
    return Harness(monkeypatch)


BODY = {"sections": [{"heading": "Mục tiêu", "blocks": [{"type": "objective", "text": "Hiểu"}]}]}


def create_item(harness):
    response = harness.post(
        "/content-items", {"kind": "lesson_plan", "title": "Giáo án 1", "body": BODY}
    )
    assert response.status_code == 201, response.text
    return response.json()


def blueprint_body(unit_id, item_type="single_choice", count=2, points="5.00"):
    slots = [
        {
            "index": i + 1,
            "itemType": item_type,
            "points": points,
            "curriculumUnitId": str(unit_id),
            "cognitiveLevel": "remember",
        }
        for i in range(count)
    ]
    return {
        "parts": [{"code": "P1", "title": "Phần 1", "slots": slots}],
        "matrix": [
            {"curriculumUnitId": str(unit_id), "cognitiveLevel": "remember", "count": count}
        ],
    }


# ---- Authentication and tenant boundaries ---------------------------------------------------


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("post", "/content-items"),
        ("get", "/content-items"),
        ("put", f"/content-items/{uuid4()}/draft"),
        ("get", "/questions"),
        ("get", "/questions/export?audience=student"),
        ("post", "/questions/import"),
        ("post", "/blueprints"),
        ("post", f"/blueprints/{uuid4()}/versions/1/publish"),
    ],
)
def test_requires_authentication(harness, method, suffix):
    for headers in ({}, {"Authorization": "Bearer bad"}):
        response = getattr(harness.client, method)(harness.url(suffix), headers=headers)
        assert response.status_code == 401
        assert set(response.json()) == {"error", "requestId"}


def test_other_workspace_is_404(harness):
    other = uuid4()
    for response in (
        harness.client.get(harness.url("/content-items", other), headers=GOOD),
        harness.client.get(harness.url(f"/questions/{uuid4()}", other), headers=GOOD),
        harness.client.get(harness.url("/blueprints", other), headers=GOOD),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "workspace_not_found"


def test_ids_from_another_workspace_are_404(harness):
    item = create_item(harness)
    # Same IDs moved to a foreign workspace: every lookup also filters workspace_id.
    for row in harness.db.store.values():
        for obj in row:
            if getattr(obj, "workspace_id", None) == harness.workspace_id:
                obj.workspace_id = uuid4()
    for suffix, code in (
        (f"/content-items/{item['id']}", "content_not_found"),
        (f"/questions/{uuid4()}", "question_not_found"),
        (f"/blueprints/{uuid4()}", "blueprint_not_found"),
    ):
        response = harness.client.get(harness.url(suffix), headers=GOOD)
        assert response.status_code == 404 and response.json()["error"]["code"] == code


def test_student_role_is_forbidden(harness):
    harness.role = "student"
    response = harness.client.get(harness.url("/questions/export?audience=student"), headers=GOOD)
    assert response.status_code == 403
    assert harness.client.get(harness.url("/content-items"), headers=GOOD).status_code == 403


@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("post", "/content-items", {"kind": "exam", "title": "x"}),
        ("post", "/content-items", {"kind": "lesson_plan", "title": "  "}),
        ("post", "/content-items", {"kind": "lesson_plan", "title": "x", "workspaceId": "y"}),
        ("get", "/content-items?limit=101", None),
        ("post", "/questions", {"stem": "x", "choices": [], "cognitiveLevel": "remember"}),
        ("get", "/questions/export?audience=parent", None),
        ("post", "/blueprints", {"title": "x"}),
    ],
)
def test_validation_errors_use_envelope(harness, method, suffix, body):
    kwargs = {"headers": GOOD} | ({"json": body} if body is not None else {})
    response = getattr(harness.client, method)(harness.url(suffix), **kwargs)
    assert response.status_code == 422
    assert set(response.json()) == {"error", "requestId"}


# ---- Content --------------------------------------------------------------------------------


def test_content_create_get_and_body_validation(harness):
    item = create_item(harness)
    assert item["latestRevisionNo"] == 1 and item["currentRevision"] is None
    assert item["latestRevision"]["status"] == "draft"
    assert item["latestRevision"]["body"]["sections"][0]["blocks"][0]["citations"] == []
    detail = harness.client.get(harness.url(f"/content-items/{item['id']}"), headers=GOOD)
    assert detail.status_code == 200 and detail.json()["latestRevision"]["revisionNo"] == 1
    bad = harness.post(
        "/content-items",
        {
            "kind": "study_guide",
            "title": "x",
            "body": {"sections": [{"heading": "", "blocks": []}]},
        },
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_content_body"
    listing = harness.client.get(harness.url("/content-items?kind=lesson_plan"), headers=GOOD)
    assert [i["id"] for i in listing.json()["items"]] == [item["id"]]


def test_revision_conflict_returns_409_with_latest_number(harness):
    item = create_item(harness)
    ok = harness.post(
        f"/content-items/{item['id']}/revisions", {"body": BODY, "expectedRevisionNo": 1}
    )
    assert ok.status_code == 201 and ok.json()["revisionNo"] == 2
    stale = harness.post(
        f"/content-items/{item['id']}/revisions", {"body": BODY, "expectedRevisionNo": 1}
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"
    assert stale.json()["error"]["latestRevisionNo"] == 2
    autosave = harness.client.put(
        harness.url(f"/content-items/{item['id']}/draft"),
        json={"body": BODY, "expectedRevisionNo": 1},
        headers=GOOD,
    )
    assert autosave.status_code == 409 and autosave.json()["error"]["latestRevisionNo"] == 2


def test_autosave_then_review_flow(harness):
    item = create_item(harness)
    path = f"/content-items/{item['id']}"
    saved = harness.client.put(
        harness.url(path + "/draft"), json={"body": BODY, "expectedRevisionNo": 1}, headers=GOOD
    )
    assert saved.status_code == 200 and set(saved.json()) == {"revisionNo", "bodySha256", "savedAt"}
    assert harness.post(path + "/revisions/1/publish").json()["error"]["code"] == (
        "revision_not_approved"
    )
    assert harness.post(path + "/revisions/1/submit").json()["status"] == "in_review"
    locked = harness.client.put(
        harness.url(path + "/draft"), json={"body": BODY, "expectedRevisionNo": 1}, headers=GOOD
    )
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "revision_not_draft"
    harness.db.staff_count = 2
    self_approve = harness.post(path + "/revisions/1/approve")
    assert self_approve.status_code == 403
    assert self_approve.json()["error"]["code"] == "self_approval_forbidden"
    harness.db.staff_count = 1
    assert (
        harness.post(path + "/revisions/1/approve", {"comment": "OK"}).json()["status"]
        == "approved"
    )
    published = harness.post(path + "/revisions/1/publish")
    assert published.status_code == 200 and published.json()["status"] == "published"
    detail = harness.client.get(harness.url(path), headers=GOOD).json()
    assert detail["status"] == "published" and detail["currentRevision"]["revisionNo"] == 1
    history = harness.client.get(harness.url(path + "/revisions"), headers=GOOD).json()
    assert [r["status"] for r in history["items"]] == ["published"]
    assert "body" not in history["items"][0]
    events = [event for event, _ in harness.audits]
    assert events == [
        "content.created",
        "content.submitted",
        "content.approved",
        "content.published",
    ]


# ---- Questions ------------------------------------------------------------------------------


QUESTION = {
    "stem": "Tập hợp rỗng có bao nhiêu phần tử?",
    "choices": [{"key": "A", "text": "0"}, {"key": "B", "text": "1"}, {"key": "C", "text": "2"}],
    "correctKey": "A",
    "explanation": "Lời giải bí mật",
    "cognitiveLevel": "remember",
    "difficulty": 1,
}


def test_teacher_question_dto_includes_key_but_listing_does_not(harness):
    created = harness.post("/questions", QUESTION | {"curriculumUnitId": str(harness.unit.id)})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["correctKey"] == "A" and body["status"] == "active"
    assert body["objectiveUnitIds"] == [str(harness.unit.id)]
    detail = harness.client.get(harness.url(f"/questions/{body['id']}"), headers=GOOD).json()
    assert detail["correctKey"] == "A"
    listing = harness.client.get(harness.url("/questions?q=r%E1%BB%97ng"), headers=GOOD).json()
    assert [q["id"] for q in listing["items"]] == [body["id"]]
    assert "correctKey" not in listing["items"][0]
    assert (
        harness.client.get(harness.url("/questions?q=100%25"), headers=GOOD).json()["items"] == []
    )
    for _, fields in harness.audits:
        assert "A" not in {str(v) for v in fields.values()}


def test_key_update_and_retire(harness):
    created = harness.post("/questions", {k: v for k, v in QUESTION.items() if k != "correctKey"})
    question_id = created.json()["id"]
    assert created.json()["correctKey"] is None and created.json()["status"] == "draft"
    keyed = harness.client.put(
        harness.url(f"/questions/{question_id}/key"), json={"correctKey": "B"}, headers=GOOD
    )
    assert keyed.json()["correctKey"] == "B" and keyed.json()["revisionNo"] == 1
    changed = harness.client.put(
        harness.url(f"/questions/{question_id}/key"), json={"correctKey": "C"}, headers=GOOD
    )
    assert changed.json()["correctKey"] == "C" and changed.json()["revisionNo"] == 2
    stale = harness.client.put(
        harness.url(f"/questions/{question_id}"),
        json=QUESTION | {"expectedRevisionNo": 1},
        headers=GOOD,
    )
    assert stale.status_code == 409 and stale.json()["error"]["latestRevisionNo"] == 2
    retired = harness.post(f"/questions/{question_id}/retire")
    assert retired.json()["status"] == "retired"
    again = harness.client.put(
        harness.url(f"/questions/{question_id}/key"), json={"correctKey": "A"}, headers=GOOD
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "question_retired"


def test_student_export_never_contains_keys(harness):
    harness.post("/questions", QUESTION)
    harness.db.statements.clear()
    response = harness.client.get(harness.url("/questions/export?audience=student"), headers=GOOD)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["cache-control"] == "no-store"
    text = response.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == list(bank.STUDENT_EXPORT_COLUMNS)
    assert "correct" not in rows[0] and "Lời giải bí mật" not in text
    assert rows[1][2:5] == ["0", "1", "2"]
    assert not any("question_key" in str(s) for s in harness.db.statements)
    teacher = harness.client.get(harness.url("/questions/export?audience=teacher"), headers=GOOD)
    rows = list(csv.reader(io.StringIO(teacher.content.decode("utf-8-sig"))))
    assert rows[0][-3:] == ["correct", "explanation", "status"]
    assert rows[1][-3:] == ["A", "Lời giải bí mật", "active"]


def test_csv_import_endpoint(harness):
    header = ",".join(bank.CSV_COLUMNS)
    text = f"{header}\nCâu một?,1,2,3,,,A,,remember,T10-01,\nCâu hai?,1,2,,,,A,,remember,,\n"
    wrong_type = harness.client.post(
        harness.url("/questions/import"),
        content=text.encode(),
        headers=GOOD | {"Content-Type": "text/plain"},
    )
    assert wrong_type.status_code == 415
    result = harness.client.post(
        harness.url("/questions/import"), content=text.encode(), headers=CSV_HEADERS
    )
    assert result.status_code == 200
    assert result.json()["created"] == 0
    assert result.json()["errors"] == [
        {"row": 3, "code": "invalid_choices", "message": "Câu hỏi cần từ 3 đến 5 phương án."}
    ]
    fixed = text.replace("Câu hai?,1,2,,", "Câu hai?,1,2,3,")
    result = harness.client.post(
        harness.url("/questions/import"), content=fixed.encode(), headers=CSV_HEADERS
    )
    assert result.json()["created"] == 2 and result.json()["errors"] == []
    again = harness.client.post(
        harness.url("/questions/import"), content=fixed.encode(), headers=CSV_HEADERS
    )
    assert again.json()["created"] == 0
    assert [d["row"] for d in again.json()["duplicates"]] == [2, 3]
    too_big = harness.client.post(
        harness.url("/questions/import"),
        content=b"a" * (api.MAX_IMPORT_BYTES + 1),
        headers=CSV_HEADERS,
    )
    assert too_big.status_code == 413
    latin = harness.client.post(
        harness.url("/questions/import"), content="Câu".encode("latin-1"), headers=CSV_HEADERS
    )
    assert latin.status_code == 422 and latin.json()["error"]["code"] == "invalid_encoding"


# ---- Blueprints -----------------------------------------------------------------------------


def blueprint_payload(harness, body=None):
    payload = {
        "title": "Kiểm tra 15 phút",
        "subjectId": str(harness.subject.id),
        "grade": 10,
        "examKind": "periodic",
        "durationMinutes": 15,
        "totalPoints": "10.00",
        "effectiveYear": 2026,
        "provenance": "Tổ Toán tự biên soạn",
    }
    return payload | ({"body": body} if body is not None else {})


def test_publish_requires_validated_version(harness):
    invalid = blueprint_body(harness.unit.id, item_type="short_answer")
    created = harness.post("/blueprints", blueprint_payload(harness, invalid))
    assert created.status_code == 201, created.text
    blueprint = created.json()
    version = blueprint["latestVersion"]
    assert version["status"] == "draft" and version["validationReport"]["ok"] is False
    assert {e["code"] for e in version["validationReport"]["errors"]} == {"unsupported_item_type"}
    refused = harness.post(f"/blueprints/{blueprint['id']}/versions/1/publish")
    assert (
        refused.status_code == 409 and refused.json()["error"]["code"] == "blueprint_not_validated"
    )

    stale = harness.post(
        f"/blueprints/{blueprint['id']}/versions",
        {"body": blueprint_body(harness.unit.id), "expectedVersionNo": 0},
    )
    assert stale.status_code == 409 and stale.json()["error"]["latestVersionNo"] == 1
    good = harness.post(
        f"/blueprints/{blueprint['id']}/versions",
        {"body": blueprint_body(harness.unit.id), "expectedVersionNo": 1},
    )
    assert good.status_code == 201 and good.json()["status"] == "validated"
    again = harness.post(f"/blueprints/{blueprint['id']}/versions/2/validate")
    assert again.json()["validationReport"]["ok"] is True
    published = harness.post(f"/blueprints/{blueprint['id']}/versions/2/publish")
    assert published.status_code == 200 and published.json()["status"] == "published"
    detail = harness.client.get(harness.url(f"/blueprints/{blueprint['id']}"), headers=GOOD).json()
    assert detail["status"] == "published" and detail["currentVersionId"] == good.json()["id"]
    assert detail["originKind"] == "teacher_defined" and detail["totalPoints"] == "10.00"
    assert [v["versionNo"] for v in detail["versions"]] == [2, 1]


def test_blueprint_points_and_unknown_unit_errors(harness):
    body = blueprint_body(harness.unit.id, points="4.00")
    created = harness.post("/blueprints", blueprint_payload(harness, body)).json()
    assert [e["code"] for e in created["latestVersion"]["validationReport"]["errors"]] == [
        "points_mismatch"
    ]
    stranger = blueprint_body(uuid4())
    version = harness.post(f"/blueprints/{created['id']}/versions", {"body": stranger}).json()
    assert [e["code"] for e in version["validationReport"]["errors"]] == ["unknown_curriculum_unit"]
    unknown_subject = harness.post(
        "/blueprints", blueprint_payload(harness) | {"subjectId": str(uuid4())}
    )
    assert unknown_subject.status_code == 422
    listing = harness.client.get(harness.url("/blueprints"), headers=GOOD).json()
    assert len(listing["items"]) == 1 and listing["nextCursor"] is None
