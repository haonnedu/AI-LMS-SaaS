"""Generation/exam/export API with TestClient, a fake token verifier and the in-memory session
(harness as in test_authoring_api.py; the router is mounted here)."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from generation_fakes import FakeStore, GenFakeSession

from app.api import generation as api
from app.api.dependencies import get_session
from app.api.identity import ApiError
from app.api.workspace_access import WorkspaceScope
from app.core.auth import CLAIM_NAMESPACE, TokenError
from app.core.config import Settings
from app.main import create_app
from app.models.authoring import (
    Blueprint,
    BlueprintVersion,
    ContentItem,
    ContentRevision,
)
from app.models.generation import ExamVersion, ExportJob, GenerationJob
from app.models.jobs import BackgroundJob
from app.models.knowledge import CurriculumUnit
from app.services import citations, llm
from app.services import question_bank as bank

GOOD = {"Authorization": "Bearer good"}
NOW = datetime(2026, 10, 23, tzinfo=UTC)


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
        self.dispatched = []

        async def dispatch(job):
            self.dispatched.append(job)
            return True

        app.state.job_dispatcher = dispatch
        self.store = FakeStore()
        app.state.object_store = self.store
        self.db = GenFakeSession()
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
        monkeypatch.setattr(api, "audit", lambda event, **f: self.audits.append((event, f)))
        self.scope = SimpleNamespace(user=self.user, workspace=workspace, role="owner")
        self.client = TestClient(app, raise_server_exceptions=False)
        self.unit = CurriculumUnit(id=uuid4(), subject_id=uuid4(), grade=6, unit_code="T6-01")
        self.db.add(self.unit)

    def url(self, suffix="", workspace_id=None):
        return f"/v1/workspaces/{workspace_id or self.workspace_id}{suffix}"

    def post(self, suffix, json=None, headers=GOOD):
        return self.client.post(self.url(suffix), json=json, headers=headers)

    def get(self, suffix):
        return self.client.get(self.url(suffix), headers=GOOD)

    async def question(self, key="A", stem=None):
        question, _ = await bank.create_question(
            self.db,
            self.scope,
            bank.QuestionInput(
                stem=stem or f"Câu hỏi {uuid4()}",
                choices=[{"key": k, "text": f"Phương án {k} {uuid4()}"} for k in "ABCD"],
                cognitive_level="remember",
                correct_key=key,
                explanation="Giải thích bí mật",
                curriculum_unit_id=self.unit.id,
            ),
        )
        return question


@pytest.fixture
def harness(monkeypatch):
    return Harness(monkeypatch)


DRAFT = {"purpose": "lesson_plan", "grade": 6, "subject": "Toán", "objectives": ["Phân số"]}


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("post", "/generation/drafts"),
        ("get", f"/generation/jobs/{uuid4()}"),
        ("get", f"/content-items/{uuid4()}/revisions/1/provenance"),
        ("post", f"/content-items/{uuid4()}/revisions/1/approve-with-provenance"),
        ("post", "/exams"),
        ("get", "/exams"),
        ("get", f"/exams/{uuid4()}/versions/1/student-view"),
        ("post", "/exports"),
        ("get", f"/exports/{uuid4()}"),
    ],
)
def test_requires_authentication(harness, method, suffix):
    response = getattr(harness.client, method)(harness.url(suffix))
    assert response.status_code == 401


def test_cross_workspace_is_404(harness):
    other = uuid4()
    for suffix in ("/exams", f"/exams/{uuid4()}", f"/exports/{uuid4()}"):
        response = harness.client.get(harness.url(suffix, other), headers=GOOD)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "workspace_not_found"
    assert harness.get(f"/exams/{uuid4()}").json()["error"]["code"] == "exam_not_found"
    assert harness.get(f"/exports/{uuid4()}").json()["error"]["code"] == "export_not_found"


def test_students_cannot_use_teacher_routes(harness):
    harness.role = "student"
    assert harness.get("/exams").status_code == 403
    assert (
        harness.post("/generation/drafts", {**DRAFT, "curriculumUnitId": str(uuid4())}).status_code
        == 403
    )


def test_request_draft_enqueues_job(harness):
    body = {**DRAFT, "curriculumUnitId": str(harness.unit.id)}
    response = harness.post("/generation/drafts", body, headers={**GOOD, "Idempotency-Key": "k1"})
    assert response.status_code == 202, response.text
    data = response.json()
    assert data["job"]["kind"] == "content.generate" and data["job"]["status"] == "queued"
    generation_job = data["generationJob"]
    assert generation_job["validationStatus"] == "pending"
    assert generation_job["promptVersion"] == "lesson_plan_v1"
    assert generation_job["provider"] == "fake" and len(harness.dispatched) == 1
    replay = harness.post("/generation/drafts", body, headers={**GOOD, "Idempotency-Key": "k1"})
    assert (
        replay.status_code == 202 and replay.json()["generationJob"]["id"] == generation_job["id"]
    )
    assert len(harness.dispatched) == 1 and len(harness.db.all(GenerationJob)) == 1
    fetched = harness.get(f"/generation/jobs/{generation_job['id']}")
    assert fetched.status_code == 200 and fetched.json()["backgroundJobId"] == data["job"]["id"]
    events = [event for event, _ in harness.audits]
    assert events == ["generation.requested"]
    assert "Phân số" not in str(harness.audits)  # objectives/prompts never audited


def test_request_draft_validation(harness):
    unknown = harness.post("/generation/drafts", {**DRAFT, "curriculumUnitId": str(uuid4())})
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "curriculum_unit_not_found"
    questions = harness.post(
        "/generation/drafts",
        {**DRAFT, "purpose": "questions", "count": 5, "curriculumUnitId": str(harness.unit.id)},
    )
    assert questions.status_code == 202 and questions.json()["job"]["kind"] == "questions.generate"
    bad = harness.post(
        "/generation/drafts", {**DRAFT, "curriculumUnitId": str(harness.unit.id), "x": 1}
    )
    assert bad.status_code == 422


def test_ai_unavailable_keeps_manual_paths(harness, monkeypatch):
    monkeypatch.setattr(llm, "provider_ready", lambda settings: False)
    response = harness.post(
        "/generation/drafts", {**DRAFT, "curriculumUnitId": str(harness.unit.id)}
    )
    assert response.status_code == 503 and response.json()["error"]["code"] == "ai_unavailable"
    assert harness.db.all(BackgroundJob) == []


# ---- Provenance -----------------------------------------------------------------------------


def content(
    harness, status="in_review", citations_=None, generation_job_id=None, audience="teacher"
):
    item = ContentItem(
        id=uuid4(),
        workspace_id=harness.workspace_id,
        kind="lesson_plan",
        title="Giáo án",
        created_by_user_id=uuid4(),
        status="in_review",
        latest_revision_no=1,
        deleted_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    revision = ContentRevision(
        id=uuid4(),
        workspace_id=harness.workspace_id,
        content_item_id=item.id,
        revision_no=1,
        body={
            "sections": [
                {
                    "heading": "Mục tiêu",
                    "blocks": [
                        {"type": "paragraph", "text": "Nội dung", "citations": citations_ or []}
                    ],
                }
            ]
        },
        audience=audience,
        status=status,
        created_by_user_id=item.created_by_user_id,
        generation_job_id=generation_job_id,
        body_sha256=b"0" * 32,
        created_at=NOW,
        updated_at=NOW,
    )
    harness.db.add(item)
    harness.db.add(revision)
    return item, revision


def resolver(active: set):
    async def resolve(db, scope, chunk_id, allow_superseded=False):
        if chunk_id not in active:
            raise ApiError(404, "citation_not_found", "x")
        return SimpleNamespace(
            chunk_id=chunk_id,
            document_id=uuid4(),
            version_id=uuid4(),
            version_status="active",
            page_no=3,
            section_path="Chương 1",
            snippet="Đoạn trích nguyên văn",
        )

    return resolve


def test_provenance_and_approval_gate(harness, monkeypatch):
    good, gone = uuid4(), uuid4()
    background = uuid4()
    harness.db.add(
        GenerationJob(
            id=uuid4(),
            workspace_id=harness.workspace_id,
            background_job_id=background,
            purpose="lesson_plan",
            prompt_version="lesson_plan_v1",
            provider="fake",
            model="fake-drafter-v1",
            validation_status="valid",
        )
    )
    item, _ = content(
        harness,
        citations_=[{"chunkId": str(good), "label": "[1]"}, {"chunkId": str(gone), "label": "[2]"}],
        generation_job_id=background,
    )
    monkeypatch.setattr(citations, "resolve_citation", resolver({good}))
    response = harness.get(f"/content-items/{item.id}/revisions/1/provenance")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["provider"] == "fake" and data["promptVersion"] == "lesson_plan_v1"
    statuses = {s["label"]: s["status"] for s in data["sources"]}
    assert statuses == {"[1]": "active", "[2]": "withdrawn"}
    withdrawn = next(s for s in data["sources"] if s["label"] == "[2]")
    assert withdrawn["snippet"] is None and withdrawn["documentId"] is None  # never fabricated
    refused = harness.post(f"/content-items/{item.id}/revisions/1/approve-with-provenance")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "citations_unresolved"

    monkeypatch.setattr(citations, "resolve_citation", resolver({good, gone}))
    approved = harness.post(f"/content-items/{item.id}/revisions/1/approve-with-provenance")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


# ---- Exams ----------------------------------------------------------------------------------


async def manual_exam(harness, points=("4", "6")):
    questions = [await harness.question(key) for key in ("B", "C")]
    response = harness.post(
        "/exams",
        {
            "title": "Đề 15 phút",
            "questionIds": [str(q.id) for q in questions],
            "points": list(points),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_exam_teacher_detail_and_student_view(harness):
    exam = await manual_exam(harness)
    items = exam["currentVersion"]["items"]
    assert [i["correctKey"] for i in items] == ["B", "C"]
    assert items[0]["explanation"] == "Giải thích bí mật"
    view = harness.get(f"/exams/{exam['id']}/versions/1/student-view")
    assert view.status_code == 200
    payload = view.json()
    for item in payload["items"]:
        assert set(item) == {"id", "position", "itemType", "stem", "choices", "points"}
    assert "Giải thích" not in view.text and "correctKey" not in view.text
    forbidden = {"correctKey", "explanation", "rationale", "correct_key"}
    assert not forbidden & set(api.StudentExamItemDTO.model_fields)
    assert not forbidden & set(api.StudentExamViewDTO.model_fields)
    listing = harness.get("/exams")
    assert listing.status_code == 200 and listing.json()["items"][0]["id"] == exam["id"]


async def test_publish_validation_and_success(harness):
    exam = await manual_exam(harness)
    first_item = exam["currentVersion"]["items"][0]["id"]
    key = harness.db.exam_keys.pop(UUID(first_item))
    refused = harness.post(f"/exams/{exam['id']}/versions/1/publish")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "exam_not_publishable"
    harness.db.exam_keys[UUID(first_item)] = key
    version = harness.db.all(ExamVersion)[0]
    version.total_points = Decimal("11")
    mismatch = harness.post(f"/exams/{exam['id']}/versions/1/publish")
    assert mismatch.status_code == 409 and "points_mismatch" in mismatch.json()["error"]["message"]
    version.total_points = Decimal("10")
    published = harness.post(f"/exams/{exam['id']}/versions/1/publish")
    assert published.status_code == 200, published.text
    current = published.json()["currentVersion"]
    assert current["status"] == "published" and len(current["contentHash"]) == 64
    again = harness.post(f"/exams/{exam['id']}/versions/1/publish")
    assert again.status_code == 409
    archived = harness.post(f"/exams/{exam['id']}/archive")
    assert archived.status_code == 200 and archived.json()["status"] == "archived"


async def test_blueprint_exam_reports_shortage(harness):
    await harness.question()
    blueprint = Blueprint(
        id=uuid4(), workspace_id=harness.workspace_id, title="BP", total_points=10
    )
    slots = [
        {
            "index": i,
            "itemType": "single_choice",
            "points": "5.00",
            "curriculumUnitId": str(harness.unit.id),
            "cognitiveLevel": "remember",
        }
        for i in (1, 2)
    ]
    version = BlueprintVersion(
        id=uuid4(),
        workspace_id=harness.workspace_id,
        blueprint_id=blueprint.id,
        version_no=1,
        status="published",
        body={"parts": [{"code": "P1", "title": "Phần 1", "slots": slots}], "matrix": []},
    )
    harness.db.add(blueprint)
    harness.db.add(version)
    short = harness.post("/exams", {"blueprintVersionId": str(version.id), "seed": "s"})
    assert short.status_code == 409
    error = short.json()["error"]
    assert error["code"] == "insufficient_pool"
    report = error["selectionReport"]
    assert report["ok"] is False and len(report["missingSlots"]) == 1
    assert report["suggestedGeneration"][0]["count"] == 1
    await harness.question()
    created = harness.post("/exams", {"blueprintVersionId": str(version.id), "seed": "s"})
    assert created.status_code == 201, created.text
    assert created.json()["selectionReport"]["ok"] is True
    assert created.json()["blueprintVersionId"] == str(version.id)


def test_exam_create_input_rules(harness):
    neither = harness.post("/exams", {"title": "Đề"})
    assert neither.status_code == 422 and neither.json()["error"]["code"] == "invalid_exam_source"
    missing_points = harness.post("/exams", {"title": "Đề", "questionIds": [str(uuid4())]})
    assert missing_points.status_code == 422
    unknown = harness.post(
        "/exams", {"title": "Đề", "questionIds": [str(uuid4())], "points": ["1"]}
    )
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "question_not_found"


# ---- Exports --------------------------------------------------------------------------------


async def test_export_audience_rules(harness):
    exam = await manual_exam(harness)
    version_id = exam["currentVersion"]["id"]
    student_draft = harness.post(
        "/exports", {"examVersionId": version_id, "format": "docx", "audience": "student"}
    )
    assert student_draft.status_code == 409
    assert student_draft.json()["error"]["code"] == "audience_not_allowed"
    teacher = harness.post(
        "/exports", {"examVersionId": version_id, "format": "docx", "audience": "teacher"}
    )
    assert teacher.status_code == 202, teacher.text
    assert teacher.json()["job"]["kind"] == "export.render"
    assert teacher.json()["exportJob"]["status"] == "queued"
    both = harness.post(
        "/exports",
        {
            "examVersionId": version_id,
            "contentRevisionId": str(uuid4()),
            "format": "docx",
            "audience": "teacher",
        },
    )
    assert both.status_code == 422
    item, revision = content(harness, status="published", audience="teacher")
    teacher_material = harness.post(
        "/exports", {"contentRevisionId": str(revision.id), "format": "pdf", "audience": "student"}
    )
    assert teacher_material.status_code == 409
    other = harness.post(
        "/exports", {"contentRevisionId": str(uuid4()), "format": "docx", "audience": "teacher"}
    )
    assert other.status_code == 404


async def test_export_download_url_only_when_succeeded(harness):
    exam = await manual_exam(harness)
    response = harness.post(
        "/exports",
        {"examVersionId": exam["currentVersion"]["id"], "format": "docx", "audience": "teacher"},
    )
    export_id = response.json()["exportJob"]["id"]
    pending = harness.get(f"/exports/{export_id}")
    assert pending.status_code == 200 and pending.json()["downloadUrl"] is None
    export = harness.db.all(ExportJob)[0]
    export.status = "succeeded"
    export.object_key = f"ws/{harness.workspace_id}/export/{export.id}.docx"
    done = harness.get(f"/exports/{export_id}")
    assert done.json()["downloadUrl"] == "https://signed.example/eduvia-de-kiem-tra-giao-vien.docx"
    assert done.json()["downloadExpiresAt"] is not None
