"""Retrieval API (KNOW-06..08) with TestClient, a fake token verifier and fake sessions,
following the harness in test_knowledge_api.py. Service-level behaviour has its own unit tests;
here we check authorization, bounds, metering, abstention, citations and job wiring."""

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import retrieval as retrieval_api
from app.api.dependencies import get_session
from app.api.identity import ApiError
from app.api.workspace_access import WorkspaceScope
from app.core.auth import CLAIM_NAMESPACE, TokenError
from app.core.config import Settings
from app.main import create_app
from app.models.documents import Document
from app.models.identity import User, Workspace
from app.models.jobs import BackgroundJob
from app.models.knowledge import EmbeddingRun
from app.services import citations, embeddings, retrieval
from app.services.embeddings import EmbeddingError, LocalHashEmbedder
from app.services.retrieval import RetrievedChunk

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


class FakeDb:
    def __init__(self):
        self.jobs: list[BackgroundJob] = []
        self.runs: list[EmbeddingRun] = []

    @asynccontextmanager
    async def begin_nested(self):
        yield

    async def flush(self):
        pass

    def add(self, obj):
        assert isinstance(obj, BackgroundJob), type(obj)
        self.jobs.append(obj)

    async def scalar(self, stmt):
        sql, values = str(stmt), stmt.compile().params
        if "count(" in sql:
            ids = {v for v in values.values() if isinstance(v, UUID)}
            return sum(1 for r in self.runs if r.document_version_id in ids)
        assert "FROM edu.background_jobs" in sql, sql
        keys = {v for v in values.values() if isinstance(v, str)}
        return next((j for j in self.jobs if j.idempotency_key in keys), None)

    async def scalars(self, stmt):
        assert "FROM edu.embedding_runs" in str(stmt)
        return Rows(sorted(self.runs, key=lambda r: r.created_at, reverse=True))


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
        if not any(route.path in paths for route in retrieval_api.router.routes):
            app.include_router(retrieval_api.router)
        app.state.token_verifier = FakeVerifier()
        self.embedder = LocalHashEmbedder()
        app.state.embedder = self.embedder
        self.db = FakeDb()
        app.dependency_overrides[get_session] = lambda: self.db
        self.dispatch = AsyncMock(return_value=True)
        app.state.job_dispatcher = self.dispatch
        self.role = "teacher"
        self.transactions = 0
        self.audits = []
        self.reservations = []
        self.retrieve_calls = []
        self.results: list[RetrievedChunk] = []
        self.documents: dict[UUID, Document] = {}
        workspace = Workspace(id=self.workspace_id, name="Cá nhân", workspace_type="personal")

        @asynccontextmanager
        async def fake_transaction(db, claims, workspace_id, *, roles=None):
            assert db is self.db and claims["sub"] == "teacher-1"
            if workspace_id != self.workspace_id:
                raise ApiError(404, "workspace_not_found", "Workspace not found.")
            if roles is not None and self.role not in roles:
                raise ApiError(403, "forbidden", "You cannot perform this action here.")
            self.transactions += 1
            yield WorkspaceScope(user=self.user, workspace=workspace, role=self.role)

        async def fake_reserve(db, scope, units, **kwargs):
            self.reservations.append((units, kwargs))

        async def fake_retrieve(db, scope, query, **kwargs):
            assert scope.workspace.id == self.workspace_id
            self.retrieve_calls.append((query, kwargs))
            return self.results[: kwargs["k"]]

        async def fake_load(db, workspace_id, document_id, **kwargs):
            document = self.documents.get(document_id)
            if document is None or document.workspace_id != workspace_id:
                raise ApiError(404, "document_not_found", "Không tìm thấy tài liệu.")
            return document

        monkeypatch.setattr(retrieval_api, "workspace_transaction", fake_transaction)
        monkeypatch.setattr(retrieval_api, "audit", lambda e, **f: self.audits.append((e, f)))
        monkeypatch.setattr(retrieval_api, "load_document", fake_load)
        monkeypatch.setattr(retrieval_api.usage, "reserve", fake_reserve)
        monkeypatch.setattr(retrieval_api.retrieval, "retrieve", fake_retrieve)
        self.client = TestClient(app, raise_server_exceptions=False)

    def url(self, suffix="", workspace_id=None):
        return f"/v1/workspaces/{workspace_id or self.workspace_id}{suffix}"

    def document(self, **overrides):
        values = dict(
            id=uuid4(),
            workspace_id=self.workspace_id,
            owner_user_id=self.user.id,
            file_name="Giáo án.txt",
            mime_type="text/plain",
            size_bytes=10,
            sha256=hashlib.sha256(b"x").digest(),
            status="uploaded",
            rights_attested=True,
            rights_scope="private",
            active_version_id=uuid4(),
            created_at=NOW,
            deleted_at=None,
        )
        values.update(overrides)
        values["object_key"] = f"ws/{values['workspace_id']}/doc/{values['id']}"
        document = Document(**values)
        self.documents[document.id] = document
        return document

    def chunk(self, text="Mệnh đề là một câu khẳng định đúng hoặc sai.", score=0.03):
        return RetrievedChunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            version_id=uuid4(),
            page_no=1,
            section_path="Chương 1",
            text=text,
            score=score,
            sources=("lexical", "semantic"),
        )


@pytest.fixture
def h(monkeypatch):
    return Harness(monkeypatch)


QUERY = {"query": "Mệnh đề là gì?"}


# ---------------------------------------------------------------- query


def test_query_requires_authentication(h):
    assert h.client.post(h.url("/retrieval/query"), json=QUERY).status_code == 401
    bad = h.client.post(h.url("/retrieval/query"), json=QUERY, headers={"Authorization": "x"})
    assert bad.status_code == 401
    assert h.retrieve_calls == [] and h.reservations == []


def test_query_other_workspace_is_404_and_never_retrieves(h):
    response = h.client.post(h.url("/retrieval/query", uuid4()), json=QUERY, headers=GOOD)
    assert response.status_code == 404 and response.json()["error"]["code"] == "workspace_not_found"
    assert h.retrieve_calls == [] and h.reservations == []


def test_query_is_teacher_only(h):
    h.role = "student"
    response = h.client.post(h.url("/retrieval/query"), json=QUERY, headers=GOOD)
    assert response.status_code == 403 and h.retrieve_calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"query": "Mệnh đề", "k": 0},
        {"query": "Mệnh đề", "k": 21},
        {"query": ""},
        {"query": "x" * 2001},
        {"query": "Mệnh đề", "documentIds": [str(uuid4()) for _ in range(51)]},
        {"query": "Mệnh đề", "documentIds": ["not-a-uuid"]},
    ],
)
def test_query_bounds_are_validated(h, body):
    response = h.client.post(h.url("/retrieval/query"), json=body, headers=GOOD)
    assert response.status_code == 422
    assert h.retrieve_calls == [] and h.reservations == []


def test_whitespace_query_is_rejected_with_vietnamese_message(h):
    response = h.client.post(h.url("/retrieval/query"), json={"query": "   "}, headers=GOOD)
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_query"
    assert "truy vấn" in response.json()["error"]["message"]


def test_empty_result_abstains(h):
    response = h.client.post(h.url("/retrieval/query"), json=QUERY, headers=GOOD)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [],
        "model": "local-hash-v1",
        "mode": "hybrid",
        "abstained": True,
    }
    assert h.reservations == [(1, {"unit_type": "embedding_ktok"})]
    assert h.transactions == 2  # meter, then re-authorize for retrieval


def test_results_carry_citations_and_snippets(h):
    long_text = "Cấp số cộng có công sai d. " * 30
    h.results = [h.chunk(), h.chunk(long_text, 0.02)]
    doc = uuid4()
    response = h.client.post(
        h.url("/retrieval/query"),
        json={"query": " Mệnh đề ", "k": 5, "documentIds": [str(doc), str(doc)]},
        headers=GOOD,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["abstained"] is False and body["mode"] == "hybrid"
    assert [i["citation"] for i in body["items"]] == ["[1]", "[2]"]
    first = body["items"][0]
    assert first["chunkId"] == str(h.results[0].chunk_id)
    assert first["versionId"] == str(h.results[0].version_id)
    assert first["pageNo"] == 1 and first["sectionPath"] == "Chương 1"
    assert len(body["items"][1]["snippet"]) <= 300 and "text" not in first
    ((query, kwargs),) = h.retrieve_calls
    assert query == "Mệnh đề" and kwargs["k"] == 5 and kwargs["document_ids"] == [doc]
    assert kwargs["model"] == "local-hash-v1" and kwargs["model_version"] == "1024d.r1"
    assert len(kwargs["query_vector"]) == embeddings.EMBEDDING_DIMENSION
    assert kwargs["max_distance"] == 0.8
    (event, fields) = h.audits[-1]
    assert event == "retrieval.query" and fields["result_count"] == 2
    assert "Mệnh đề" not in repr(fields)  # queries are never audited


def test_provider_failure_degrades_to_lexical_never_wider(h):
    class Down(LocalHashEmbedder):
        def embed(self, texts):
            raise EmbeddingError("provider_unavailable", units=3)

    h.client.app.state.embedder = Down()
    h.results = [h.chunk()]
    response = h.client.post(h.url("/retrieval/query"), json=QUERY, headers=GOOD)
    assert response.status_code == 200 and response.json()["mode"] == "lexical"
    ((_, kwargs),) = h.retrieve_calls
    assert kwargs["query_vector"] is None and kwargs["model"] is None
    assert kwargs["document_ids"] is None


def test_quota_exhaustion_blocks_query(h, monkeypatch):
    async def exhausted(*args, **kwargs):
        raise ApiError(429, "quota_exceeded", "Không gian làm việc đã dùng hết hạn mức.")

    monkeypatch.setattr(retrieval_api.usage, "reserve", exhausted)
    response = h.client.post(h.url("/retrieval/query"), json=QUERY, headers=GOOD)
    assert response.status_code == 429 and h.retrieve_calls == []


# ---------------------------------------------------------------- citations


def test_citation_preview_and_404(h, monkeypatch):
    chunk_id = uuid4()
    calls = []

    async def resolve(db, scope, cid, *, allow_superseded=False):
        calls.append((cid, allow_superseded))
        if cid != chunk_id:
            raise ApiError(404, "citation_not_found", "Không tìm thấy nguồn trích dẫn.")
        return citations.CitationPreview(
            chunk_id=cid,
            document_id=uuid4(),
            version_id=uuid4(),
            version_no=1,
            version_status="active",
            file_name="Giáo án.txt",
            page_no=2,
            section_path="Bài 1",
            char_start=0,
            char_end=10,
            snippet="Mệnh đề",
            text="Mệnh đề là…",
            text_sha256="ab" * 32,
            activated_at=NOW,
        )

    monkeypatch.setattr(retrieval_api.citations, "resolve_citation", resolve)
    ok = h.client.get(h.url(f"/citations/{chunk_id}?allowSuperseded=true"), headers=GOOD)
    assert ok.status_code == 200, ok.text
    assert ok.json()["pageNo"] == 2 and ok.json()["versionStatus"] == "active"
    missing = h.client.get(h.url(f"/citations/{uuid4()}"), headers=GOOD)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "citation_not_found"
    assert calls[0] == (chunk_id, True) and calls[1][1] is False
    other = h.client.get(h.url(f"/citations/{chunk_id}", uuid4()), headers=GOOD)
    assert other.status_code == 404 and len(calls) == 2


# ---------------------------------------------------------------- embedding jobs and runs


def test_embed_enqueues_one_job_per_version_and_model(h):
    document = h.document()
    first = h.client.post(h.url(f"/documents/{document.id}/embed"), headers=GOOD)
    assert first.status_code == 202, first.text
    job = first.json()["job"]
    assert job["kind"] == "document.embed" and job["status"] == "queued"
    again = h.client.post(h.url(f"/documents/{document.id}/embed"), headers=GOOD)
    assert again.json()["job"]["id"] == job["id"]
    assert h.dispatch.await_count == 1 and len(h.db.jobs) == 1
    key = h.db.jobs[0].idempotency_key
    assert key.startswith("system:document.embed:" + str(document.active_version_id))
    assert key.endswith(":local-hash-v1:1024d.r1:0")
    # A finished run allows a fresh attempt.
    h.db.runs.append(
        EmbeddingRun(id=uuid4(), document_version_id=document.active_version_id, created_at=NOW)
    )
    third = h.client.post(h.url(f"/documents/{document.id}/embed"), headers=GOOD)
    assert third.json()["job"]["id"] != job["id"] and h.dispatch.await_count == 2


def test_embed_retries_a_failed_job_with_the_same_key(h):
    document = h.document()
    first = h.client.post(h.url(f"/documents/{document.id}/embed"), headers=GOOD)
    h.db.jobs[0].status, h.db.jobs[0].error_code = "failed", "transient_error"
    again = h.client.post(h.url(f"/documents/{document.id}/embed"), headers=GOOD)
    assert again.json()["job"]["id"] == first.json()["job"]["id"]
    assert again.json()["job"]["status"] == "queued" and h.dispatch.await_count == 2


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"status": "pending"}, "document_not_ready"),
        ({"active_version_id": None}, "document_not_ready"),
        ({"rights_attested": False}, "rights_attestation_required"),
    ],
)
def test_embed_refuses_unready_documents(h, overrides, code):
    document = h.document(**overrides)
    response = h.client.post(h.url(f"/documents/{document.id}/embed"), headers=GOOD)
    assert response.status_code == 409 and response.json()["error"]["code"] == code
    assert h.db.jobs == []


def test_embed_cross_workspace_document_is_404(h):
    foreign = h.document(workspace_id=uuid4())
    response = h.client.post(h.url(f"/documents/{foreign.id}/embed"), headers=GOOD)
    assert response.status_code == 404 and h.db.jobs == []


def test_embedding_runs_listing(h):
    document = h.document()
    h.db.runs.append(
        EmbeddingRun(
            id=uuid4(),
            document_version_id=document.active_version_id,
            job_id=None,
            model="local-hash-v1",
            version="1024d.r1",
            status="failed",
            chunk_count=4,
            units=2,
            error_code="provider_unavailable",
            provider_request_ids=["r1"],
            created_at=NOW,
            finished_at=NOW,
        )
    )
    response = h.client.get(h.url(f"/documents/{document.id}/embedding-runs"), headers=GOOD)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["currentModel"] == "local-hash-v1" and body["currentVersion"] == "1024d.r1"
    (run,) = body["items"]
    assert run["status"] == "failed" and run["errorCode"] == "provider_unavailable"
    assert "providerRequestIds" not in run
    h.role = "student"
    forbidden = h.client.get(h.url(f"/documents/{document.id}/embedding-runs"), headers=GOOD)
    assert forbidden.status_code == 403


def test_router_shape():
    paths = {(route.path, tuple(sorted(route.methods))) for route in retrieval_api.router.routes}
    assert paths == {
        ("/v1/workspaces/{workspace_id}/retrieval/query", ("POST",)),
        ("/v1/workspaces/{workspace_id}/citations/{chunk_id}", ("GET",)),
        ("/v1/workspaces/{workspace_id}/documents/{document_id}/embed", ("POST",)),
        ("/v1/workspaces/{workspace_id}/documents/{document_id}/embedding-runs", ("GET",)),
    }
    assert retrieval.MAX_K == 20
