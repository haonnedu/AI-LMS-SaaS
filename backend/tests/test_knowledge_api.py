"""Knowledge API (curriculum, versions, chunks, re-ingest, tags) with TestClient, a fake token
verifier and a fake session, following the harness in test_documents_api.py."""

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import knowledge as knowledge_api
from app.api.dependencies import get_session
from app.api.identity import ApiError
from app.api.workspace_access import WorkspaceScope
from app.core.auth import CLAIM_NAMESPACE, TokenError
from app.core.config import Settings
from app.main import create_app
from app.models.documents import Document
from app.models.identity import User, Workspace
from app.models.jobs import BackgroundJob
from app.models.knowledge import (
    CurriculumSubject,
    CurriculumUnit,
    DocumentChunk,
    DocumentCurriculumTag,
    DocumentVersion,
)

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
GOOD = {"Authorization": "Bearer good"}


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


class Rows(list):
    def all(self):
        return list(self)


def params(stmt) -> dict:
    return stmt.compile().params


def uuids(values) -> set[UUID]:
    found = set()
    for value in values:
        if isinstance(value, UUID):
            found.add(value)
        elif isinstance(value, list | tuple):
            found |= {v for v in value if isinstance(v, UUID)}
    return found


class FakeDb:
    """Answers the queries the knowledge router issues, keyed by the table they read."""

    def __init__(self):
        self.documents: list[Document] = []
        self.jobs: list[BackgroundJob] = []
        self.subjects: list[CurriculumSubject] = []
        self.units: list[CurriculumUnit] = []
        self.versions: list[DocumentVersion] = []
        self.chunks: list[DocumentChunk] = []
        self.tags: list[DocumentCurriculumTag] = []
        self.transactions = 0

    @asynccontextmanager
    async def begin(self):
        self.transactions += 1
        yield

    @asynccontextmanager
    async def begin_nested(self):
        yield

    async def flush(self):
        pass

    def add(self, obj):
        if isinstance(obj, BackgroundJob):
            self.jobs.append(obj)
        elif isinstance(obj, DocumentCurriculumTag):
            self.tags.append(obj)
        else:
            raise AssertionError(type(obj))

    async def execute(self, stmt):
        sql = str(stmt)
        assert sql.startswith("DELETE FROM edu.document_curriculum_tags"), sql
        ids = uuids(params(stmt).values())
        self.tags = [t for t in self.tags if not {t.document_id, t.workspace_id} <= ids]

    async def scalar(self, stmt):
        sql, values = str(stmt), params(stmt)
        ids, keys = uuids(values.values()), {v for v in values.values() if isinstance(v, str)}
        if "FROM edu.background_jobs" in sql:
            return next((j for j in self.jobs if j.idempotency_key in keys), None)
        if "FROM edu.document_versions" in sql:
            return next(
                (v for v in self.versions if {v.id, v.workspace_id, v.document_id} <= ids), None
            )
        assert "FROM edu.documents" in sql, sql
        return next((d for d in self.documents if {d.id, d.workspace_id} <= ids), None)

    async def scalars(self, stmt):
        sql, values = str(stmt), params(stmt)
        ids = uuids(values.values())
        if "FROM edu.document_chunks" in sql:
            after = values.get("chunk_index_1", -1)
            rows = sorted(
                (
                    c
                    for c in self.chunks
                    if {c.document_version_id, c.workspace_id} <= ids and c.chunk_index > after
                ),
                key=lambda c: c.chunk_index,
            )
            return Rows(rows[: values["param_1"]])
        if "FROM edu.document_versions" in sql:
            rows = [v for v in self.versions if {v.document_id, v.workspace_id} <= ids]
            return Rows(sorted(rows, key=lambda v: -v.version_no))
        if "document_curriculum_tags" in sql:
            tagged = {
                t.curriculum_unit_id for t in self.tags if {t.document_id, t.workspace_id} <= ids
            }
            return Rows(sorted((u for u in self.units if u.id in tagged), key=self._order))
        if len(stmt.selected_columns) == 1:  # SELECT curriculum_units.id WHERE id IN (...)
            return Rows([u.id for u in self.units if u.id in ids])
        if "FROM edu.curriculum_units" in sql:
            rows = self.units
            if "code_1" in values:
                subject = {s.id for s in self.subjects if s.code == values["code_1"]}
                rows = [u for u in rows if u.subject_id in subject]
            if "grade_1" in values:
                rows = [u for u in rows if u.grade == values["grade_1"]]
            if "program_year_1" in values:
                rows = [u for u in rows if u.program_year == values["program_year_1"]]
            return Rows(sorted(rows, key=self._order))
        assert "FROM edu.curriculum_subjects" in sql, sql
        return Rows(sorted(self.subjects, key=lambda s: s.code))

    @staticmethod
    def _order(unit):
        return (unit.grade, unit.sort_order, unit.unit_code)


class Harness:
    def __init__(self, monkeypatch):
        self.workspace_id = uuid4()
        self.user = User(id=uuid4(), provider_issuer="https://identity.example/")
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
        if not any(route.path in paths for route in knowledge_api.router.routes):
            app.include_router(knowledge_api.router)
        app.state.token_verifier = FakeVerifier()
        self.db = FakeDb()
        app.dependency_overrides[get_session] = lambda: self.db
        self.dispatch = AsyncMock(return_value=True)
        app.state.job_dispatcher = self.dispatch
        self.audits = []
        self.role = "owner"
        workspace = Workspace(id=self.workspace_id, name="Cá nhân", workspace_type="personal")

        @asynccontextmanager
        async def fake_transaction(db, claims, workspace_id, *, roles=None):
            assert db is self.db and claims["sub"] == "teacher-1"
            if workspace_id != self.workspace_id:
                raise ApiError(404, "workspace_not_found", "Workspace not found.")
            if roles is not None and self.role not in roles:
                raise ApiError(403, "forbidden", "You cannot perform this action here.")
            yield WorkspaceScope(user=self.user, workspace=workspace, role=self.role)

        async def fake_authenticated(db, claims):
            assert db is self.db and claims["sub"] == "teacher-1"

        def fake_audit(event, **fields):
            self.audits.append((event, fields))

        monkeypatch.setattr(knowledge_api, "workspace_transaction", fake_transaction)
        monkeypatch.setattr(knowledge_api, "authenticated", fake_authenticated)
        monkeypatch.setattr(knowledge_api, "audit", fake_audit)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.seed_curriculum()

    def seed_curriculum(self):
        self.toan = CurriculumSubject(id=uuid4(), code="toan", name_vi="Toán")
        van = CurriculumSubject(id=uuid4(), code="ngu-van", name_vi="Ngữ văn")
        self.db.subjects += [self.toan, van]
        for grade, code, title, order in [
            (10, "T10-02", "Bất phương trình", 2),
            (10, "T10-01", "Mệnh đề và tập hợp", 1),
            (11, "T11-01", "Hàm số lượng giác", 1),
        ]:
            self.db.units.append(
                CurriculumUnit(
                    id=uuid4(),
                    subject_id=self.toan.id,
                    grade=grade,
                    program_year="2018",
                    unit_code=code,
                    title_vi=title,
                    parent_id=None,
                    sort_order=order,
                    source_provenance="seed:pilot-draft",
                    version=1,
                )
            )

    def url(self, suffix="", workspace_id=None):
        return f"/v1/workspaces/{workspace_id or self.workspace_id}{suffix}"

    def document(self, status="uploaded", **overrides):
        values = dict(
            id=uuid4(),
            workspace_id=self.workspace_id,
            owner_user_id=self.user.id,
            file_name="Giáo án.txt",
            mime_type="text/plain",
            size_bytes=10,
            sha256=hashlib.sha256(b"x").digest(),
            status=status,
            rights_attested=True,
            rights_scope="private",
            active_version_id=None,
            created_at=NOW,
            deleted_at=NOW if status == "deleted" else None,
        )
        values.update(overrides)
        values["object_key"] = f"ws/{values['workspace_id']}/doc/{values['id']}"
        document = Document(**values)
        self.db.documents.append(document)
        return document

    def version(self, document, version_no=1, status="active", **overrides):
        values = dict(
            id=uuid4(),
            workspace_id=document.workspace_id,
            document_id=document.id,
            version_no=version_no,
            status=status,
            parser="text",
            parser_version="1",
            chunker_version="1",
            page_count=None,
            char_count=100,
            chunk_count=0,
            text_sha256=hashlib.sha256(b"t").digest() if status != "failed" else None,
            error_code=None,
            created_at=NOW,
            activated_at=NOW if status in {"active", "superseded"} else None,
        )
        values.update(overrides)
        version = DocumentVersion(**values)
        self.db.versions.append(version)
        if status == "active":
            document.active_version_id = version.id
        return version

    def chunks(self, version, count):
        for index in range(count):
            text = f"Đoạn {index}."
            self.db.chunks.append(
                DocumentChunk(
                    id=uuid4(),
                    workspace_id=version.workspace_id,
                    document_version_id=version.id,
                    chunk_index=index,
                    page_no=1,
                    section_path="Chương 1",
                    char_start=index * 10,
                    char_end=index * 10 + len(text),
                    text=text,
                    text_sha256=hashlib.sha256(text.encode()).digest(),
                    token_estimate=3,
                )
            )


@pytest.fixture
def harness(monkeypatch):
    return Harness(monkeypatch)


def test_requires_authentication(harness):
    document_id = uuid4()
    for method, path in [
        ("get", "/v1/curriculum/subjects"),
        ("get", "/v1/curriculum/units"),
        ("get", harness.url(f"/documents/{document_id}/versions")),
        ("get", harness.url(f"/documents/{document_id}/versions/{uuid4()}/chunks")),
        ("post", harness.url(f"/documents/{document_id}/reingest")),
        ("get", harness.url(f"/documents/{document_id}/curriculum-tags")),
        ("put", harness.url(f"/documents/{document_id}/curriculum-tags")),
    ]:
        response = harness.client.request(method, path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "unauthorized"
    bad = harness.client.get("/v1/curriculum/subjects", headers={"Authorization": "Bearer bad"})
    assert bad.status_code == 401


def test_curriculum_listing(harness):
    subjects = harness.client.get("/v1/curriculum/subjects", headers=GOOD)
    assert subjects.status_code == 200
    assert [s["code"] for s in subjects.json()["items"]] == ["ngu-van", "toan"]
    assert subjects.json()["items"][1]["nameVi"] == "Toán"
    units = harness.client.get("/v1/curriculum/units?subject=toan&grade=10", headers=GOOD)
    assert units.status_code == 200
    body = units.json()["items"]
    assert [u["unitCode"] for u in body] == ["T10-01", "T10-02"]
    assert body[0]["sourceProvenance"] == "seed:pilot-draft" and body[0]["programYear"] == "2018"
    everything = harness.client.get("/v1/curriculum/units", headers=GOOD).json()["items"]
    assert len(everything) == 3
    none = harness.client.get("/v1/curriculum/units?subject=ngu-van", headers=GOOD)
    assert none.json()["items"] == []
    for query in ("grade=13", "subject=Toan!", "programYear=18"):
        assert harness.client.get(f"/v1/curriculum/units?{query}", headers=GOOD).status_code == 422


def test_cross_workspace_and_unknown_document_are_404(harness):
    document = harness.document()
    version = harness.version(document)
    other = uuid4()
    for method, suffix in [
        ("get", f"/documents/{document.id}/versions"),
        ("get", f"/documents/{document.id}/versions/{version.id}/chunks"),
        ("post", f"/documents/{document.id}/reingest"),
        ("get", f"/documents/{document.id}/curriculum-tags"),
    ]:
        response = harness.client.request(method, harness.url(suffix, other), headers=GOOD)
        assert (response.status_code, response.json()["error"]["code"]) == (
            404,
            "workspace_not_found",
        )
    missing = harness.client.get(harness.url(f"/documents/{uuid4()}/versions"), headers=GOOD)
    assert missing.json()["error"]["code"] == "document_not_found"
    deleted = harness.document(status="deleted")
    gone = harness.client.get(harness.url(f"/documents/{deleted.id}/versions"), headers=GOOD)
    assert gone.status_code == 404
    # A version of another document is not reachable through this document.
    sibling = harness.document()
    cross = harness.client.get(
        harness.url(f"/documents/{sibling.id}/versions/{version.id}/chunks"), headers=GOOD
    )
    assert (cross.status_code, cross.json()["error"]["code"]) == (404, "version_not_found")
    assert harness.dispatch.await_count == 0


def test_students_cannot_read_chunks(harness):
    document = harness.document()
    version = harness.version(document)
    harness.role = "student"
    response = harness.client.get(
        harness.url(f"/documents/{document.id}/versions/{version.id}/chunks"), headers=GOOD
    )
    assert response.status_code == 403


def test_versions_listing_shows_failed_reason(harness):
    document = harness.document()
    old = harness.version(document, 1, status="superseded")
    active = harness.version(document, 2, status="active", chunk_count=4)
    harness.version(document, 3, status="failed", error_code="no_text_layer", char_count=0)
    response = harness.client.get(harness.url(f"/documents/{document.id}/versions"), headers=GOOD)
    assert response.status_code == 200
    body = response.json()
    assert body["activeVersionId"] == str(active.id)
    assert [(v["versionNo"], v["status"]) for v in body["items"]] == [
        (3, "failed"),
        (2, "active"),
        (1, "superseded"),
    ]
    failed = body["items"][0]
    assert failed["errorCode"] == "no_text_layer" and "OCR" in failed["errorMessage"]
    assert failed["textSha256"] is None
    assert body["items"][2]["id"] == str(old.id) and body["items"][2]["errorMessage"] is None


def test_chunks_pagination(harness):
    document = harness.document()
    version = harness.version(document)
    harness.chunks(version, 5)
    url = harness.url(f"/documents/{document.id}/versions/{version.id}/chunks")
    first = harness.client.get(url + "?limit=2", headers=GOOD).json()
    assert [c["chunkIndex"] for c in first["items"]] == [0, 1]
    assert first["items"][0]["text"] == "Đoạn 0." and first["items"][0]["sectionPath"] == "Chương 1"
    second = harness.client.get(f"{url}?limit=2&cursor={first['nextCursor']}", headers=GOOD).json()
    assert [c["chunkIndex"] for c in second["items"]] == [2, 3]
    last = harness.client.get(f"{url}?limit=2&cursor={second['nextCursor']}", headers=GOOD).json()
    assert [c["chunkIndex"] for c in last["items"]] == [4] and last["nextCursor"] is None
    bad = harness.client.get(url + "?cursor=@@", headers=GOOD)
    assert (bad.status_code, bad.json()["error"]["code"]) == (422, "invalid_cursor")


def test_reingest_enqueues_once_per_pipeline_version(harness):
    document = harness.document()
    first = harness.client.post(harness.url(f"/documents/{document.id}/reingest"), headers=GOOD)
    assert first.status_code == 202, first.text
    job = first.json()["job"]
    assert (job["kind"], job["status"]) == ("document.reingest", "queued")
    assert harness.db.jobs[0].input == {"documentId": str(document.id)}
    assert harness.db.jobs[0].idempotency_key.startswith("system:document.reingest:")
    again = harness.client.post(harness.url(f"/documents/{document.id}/reingest"), headers=GOOD)
    assert again.json()["job"]["id"] == job["id"]
    assert harness.dispatch.await_count == 1
    assert [event for event, _ in harness.audits] == ["document.reingest"]
    keyed = harness.client.post(
        harness.url(f"/documents/{document.id}/reingest"),
        headers={**GOOD, "Idempotency-Key": "retry-1"},
    )
    assert keyed.status_code == 202 and keyed.json()["job"]["id"] != job["id"]


def test_reingest_requires_rights_and_published_document(harness):
    unattested = harness.document(rights_attested=False)
    response = harness.client.post(
        harness.url(f"/documents/{unattested.id}/reingest"), headers=GOOD
    )
    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "rights_attestation_required",
    )
    pending = harness.document(status="pending")
    response = harness.client.post(harness.url(f"/documents/{pending.id}/reingest"), headers=GOOD)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "document_not_ready")
    assert harness.db.jobs == [] and harness.dispatch.await_count == 0


def test_curriculum_tags_replace_set(harness):
    document = harness.document()
    url = harness.url(f"/documents/{document.id}/curriculum-tags")
    unit_a, unit_b, unit_c = harness.db.units
    assert harness.client.get(url, headers=GOOD).json()["items"] == []
    first = harness.client.put(
        url, json={"unitIds": [str(unit_a.id), str(unit_b.id), str(unit_a.id)]}, headers=GOOD
    )
    assert first.status_code == 200, first.text
    assert [u["unitCode"] for u in first.json()["items"]] == ["T10-01", "T10-02"]
    replaced = harness.client.put(url, json={"unitIds": [str(unit_c.id)]}, headers=GOOD)
    assert [u["unitCode"] for u in replaced.json()["items"]] == ["T11-01"]
    assert [u["unitCode"] for u in harness.client.get(url, headers=GOOD).json()["items"]] == [
        "T11-01"
    ]
    assert all(t.workspace_id == harness.workspace_id for t in harness.db.tags)
    cleared = harness.client.put(url, json={"unitIds": []}, headers=GOOD)
    assert cleared.json()["items"] == [] and harness.db.tags == []
    assert [event for event, _ in harness.audits].count("document.curriculum_tags") == 3


def test_curriculum_tags_validation(harness):
    document = harness.document()
    url = harness.url(f"/documents/{document.id}/curriculum-tags")
    unknown = harness.client.put(url, json={"unitIds": [str(uuid4())]}, headers=GOOD)
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (
        422,
        "curriculum_unit_not_found",
    )
    too_many = harness.client.put(
        url, json={"unitIds": [str(uuid4()) for _ in range(51)]}, headers=GOOD
    )
    assert too_many.status_code == 422
    assert harness.client.put(url, json={"unitIds": ["nope"]}, headers=GOOD).status_code == 422
    other = harness.client.put(
        harness.url(f"/documents/{uuid4()}/curriculum-tags"), json={"unitIds": []}, headers=GOOD
    )
    assert other.status_code == 404
    assert harness.db.tags == []
