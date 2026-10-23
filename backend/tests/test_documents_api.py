"""Document API with TestClient, a fake token verifier, fake session and stubbed S3."""

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from urllib.parse import quote
from uuid import UUID, uuid4

import boto3
import pytest
from botocore.config import Config
from botocore.stub import ANY, Stubber
from fastapi.testclient import TestClient

from app.api import documents as documents_api
from app.api import jobs as jobs_api
from app.api.dependencies import get_session
from app.api.identity import ApiError
from app.api.workspace_access import WorkspaceScope
from app.core.auth import CLAIM_NAMESPACE, TokenError
from app.core.config import Settings
from app.main import create_app
from app.models.documents import Document
from app.models.identity import User, Workspace
from app.models.jobs import BackgroundJob, WorkspaceQuota
from app.services import jobs as job_service
from app.services.storage import ObjectStore

MIB = 1024 * 1024
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


class FakeResult(list):
    def all(self):
        return list(self)


class FakeDb:
    """Answers the few queries the routers issue, keyed by the table they read."""

    def __init__(self):
        self.jobs: list[BackgroundJob] = []
        self.documents: list[Document] = []
        self.quota = WorkspaceQuota(month_cap_units=1000)
        self.used = 0
        self.added = []

    async def scalar(self, stmt):
        sql = str(stmt)
        if "workspace_quotas" in sql:
            return self.quota
        if "sum(" in sql:
            return self.used
        rows = self.jobs if "FROM edu.background_jobs" in sql else self.documents
        params = stmt.compile().params
        ids = {value for value in params.values() if isinstance(value, UUID)}
        keys = {value for value in params.values() if isinstance(value, str)}
        for row in rows:
            if row.id in ids or getattr(row, "idempotency_key", None) in keys:
                return row
        return None

    async def scalars(self, stmt):
        sql = str(stmt)
        return FakeResult(self.jobs if "FROM edu.background_jobs" in sql else self.documents)

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, BackgroundJob):
            self.jobs.append(obj)
        elif isinstance(obj, Document):
            self.documents.append(obj)

    async def flush(self):
        pass

    @asynccontextmanager
    async def begin_nested(self):
        yield


class Harness:
    def __init__(self, monkeypatch, upload_max_bytes=MIB):
        self.workspace_id = uuid4()
        self.user = User(id=uuid4(), provider_issuer="https://identity.example/")
        self.settings = Settings(
            _env_file=None,
            environment="test",
            database_url="postgresql+psycopg://eduvia_runtime:x@localhost/eduvia_test",
            auth_issuer="https://identity.example/",
            auth_audience="eduvia-api",
            auth_jwks_url="https://identity.example/jwks",
            s3_bucket="eduvia-test",
            upload_max_bytes=upload_max_bytes,
        )
        app = create_app(self.settings)
        paths = {getattr(route, "path", "") for route in app.routes}
        for router in (documents_api.router, jobs_api.router):
            if not any(route.path in paths for route in router.routes):
                app.include_router(router)
        app.state.token_verifier = FakeVerifier()
        self.db = FakeDb()
        app.dependency_overrides[get_session] = lambda: self.db
        self.dispatch = AsyncMock(return_value=True)
        app.state.job_dispatcher = self.dispatch
        self.s3 = boto3.client(
            "s3",
            region_name="us-east-1",
            endpoint_url="http://127.0.0.1:9000",
            aws_access_key_id="test-access",
            aws_secret_access_key="test-secret",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self.stub = Stubber(self.s3)
        self.stub.activate()
        app.state.object_store = ObjectStore(self.settings, client=self.s3)
        self.audits = []
        workspace = Workspace(id=self.workspace_id, name="Cá nhân", workspace_type="personal")

        @asynccontextmanager
        async def fake_transaction(db, claims, workspace_id, *, roles=None):
            assert db is self.db and claims["sub"] == "teacher-1"
            if workspace_id != self.workspace_id:
                raise ApiError(404, "workspace_not_found", "Workspace not found.")
            yield WorkspaceScope(user=self.user, workspace=workspace, role="owner")

        def fake_audit(event, **fields):
            self.audits.append((event, fields))

        for module in (documents_api, jobs_api):
            monkeypatch.setattr(module, "workspace_transaction", fake_transaction)
            monkeypatch.setattr(module, "audit", fake_audit)
        self.client = TestClient(app, raise_server_exceptions=False)

    def url(self, suffix="", workspace_id=None):
        return f"/v1/workspaces/{workspace_id or self.workspace_id}{suffix}"

    def expect_put(self, body: bytes):
        self.stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "eduvia-test",
                "Key": ANY,
                "Body": ANY,
                "ContentType": "application/pdf",
                "ContentLength": len(body),
                "ChecksumSHA256": ANY,
            },
        )

    def expect_delete(self):
        self.stub.add_response("delete_object", {}, {"Bucket": "eduvia-test", "Key": ANY})

    def document(self, status="uploaded", **overrides):
        values = dict(
            id=uuid4(),
            workspace_id=self.workspace_id,
            owner_user_id=self.user.id,
            file_name="Đề 1.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256=hashlib.sha256(b"x").digest(),
            status=status,
            rights_attested=True,
            created_at=NOW,
            deleted_at=NOW if status == "deleted" else None,
        )
        values.update(overrides)
        values["object_key"] = f"ws/{values['workspace_id']}/doc/{values['id']}"
        document = Document(**values)
        self.db.documents.append(document)
        return document

    def job(self, status="queued", **overrides):
        values = dict(
            id=uuid4(),
            workspace_id=self.workspace_id,
            requested_by_user_id=self.user.id,
            kind="document.ingest",
            status=status,
            idempotency_key="client:" + str(uuid4()),
            request_hash="h",
            attempt=0,
            max_attempts=3,
            cancel_requested=False,
            input={},
            created_at=NOW,
            updated_at=NOW,
        )
        values.update(overrides)
        job = BackgroundJob(**values)
        self.db.jobs.append(job)
        return job


@pytest.fixture
def harness(monkeypatch):
    h = Harness(monkeypatch)
    yield h
    h.stub.assert_no_pending_responses()
    h.stub.deactivate()


PDF = b"%PDF-1.7\n" + b"0" * 100


def upload_headers(**overrides):
    headers = {
        **GOOD,
        "Content-Type": "application/pdf",
        "X-File-Name": quote("Giáo án.pdf"),
        "X-Rights-Attested": "true",
    }
    headers.update(overrides)
    return {k: v for k, v in headers.items() if v is not None}


def test_requires_authentication(harness):
    for method, suffix in [
        ("post", "/documents"),
        ("get", "/documents"),
        ("delete", f"/documents/{uuid4()}"),
    ]:
        response = harness.client.request(method, harness.url(suffix))
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
    bad = harness.client.get(harness.url("/documents"), headers={"Authorization": "Bearer bad"})
    assert bad.status_code == 401


def test_cross_workspace_is_404_and_stores_nothing(harness):
    other = uuid4()
    response = harness.client.post(
        harness.url("/documents", other), content=PDF, headers=upload_headers()
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "workspace_not_found"
    assert harness.client.get(harness.url("/documents", other), headers=GOOD).status_code == 404
    assert harness.db.documents == [] and harness.dispatch.await_count == 0


def test_missing_rights_attestation_is_422(harness):
    for value in (None, "false", "yes"):
        response = harness.client.post(
            harness.url("/documents"),
            content=PDF,
            headers=upload_headers(**{"X-Rights-Attested": value}),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "rights_attestation_required"


def test_oversize_is_413_by_header_and_by_stream(harness):
    big = b"%PDF-" + b"0" * MIB
    response = harness.client.post(harness.url("/documents"), content=big, headers=upload_headers())
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"

    def chunked():
        yield b"%PDF-"
        for _ in range(5):
            yield b"0" * (MIB // 4)

    response = harness.client.post(
        harness.url("/documents"), content=chunked(), headers=upload_headers()
    )
    assert response.status_code == 413


@pytest.mark.parametrize(
    "overrides,status,code",
    [
        ({"Content-Type": "image/png"}, 415, "unsupported_media_type"),
        ({"X-File-Name": "..%2Fx.pdf"}, 422, "invalid_file_name"),
        ({"X-File-Name": "a.txt"}, 422, "file_type_mismatch"),
        ({"Idempotency-Key": "x" * 200}, 422, "invalid_idempotency_key"),
    ],
)
def test_upload_validation(harness, overrides, status, code):
    response = harness.client.post(
        harness.url("/documents"), content=PDF, headers=upload_headers(**overrides)
    )
    assert (response.status_code, response.json()["error"]["code"]) == (status, code)


def test_content_sniffing_rejects_before_storage(harness):
    response = harness.client.post(
        harness.url("/documents"), content=b"MZ not a pdf", headers=upload_headers()
    )
    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "invalid_file_content",
    )


def test_upload_happy_path(harness):
    harness.expect_put(PDF)
    response = harness.client.post(
        harness.url("/documents"), content=PDF, headers=upload_headers(**{"Idempotency-Key": "k1"})
    )
    assert response.status_code == 202, response.text
    body = response.json()
    document, job = body["document"], body["job"]
    assert document["fileName"] == "Giáo án.pdf"
    assert document["status"] == "pending" and document["rightsAttested"] is True
    assert document["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert document["sizeBytes"] == len(PDF)
    assert (job["kind"], job["status"], job["attempt"]) == ("document.ingest", "queued", 0)
    assert "objectKey" not in document and "ws/" not in response.text
    stored = harness.db.documents[0]
    assert stored.object_key == f"ws/{harness.workspace_id}/doc/{stored.id}"
    assert harness.db.jobs[0].idempotency_key == "client:k1"
    assert harness.db.jobs[0].input == {"documentId": document["id"]}
    reservation = [e for e in harness.db.added if e.__class__.__name__ == "UsageEvent"]
    assert [(e.kind, e.units) for e in reservation] == [("reservation", 1)]
    harness.dispatch.assert_awaited_once()
    assert harness.audits[0][0] == "document.upload"


def test_quota_exceeded_discards_object(harness):
    harness.db.used = 1000
    harness.expect_put(PDF)
    harness.expect_delete()
    response = harness.client.post(harness.url("/documents"), content=PDF, headers=upload_headers())
    assert (response.status_code, response.json()["error"]["code"]) == (429, "quota_exceeded")
    assert harness.dispatch.await_count == 0


def test_idempotent_replay_returns_original(harness):
    original = harness.document(status="pending")
    digest = job_service.request_hash(
        "document.upload",
        {
            "fileName": "Giáo án.pdf",
            "mimeType": "application/pdf",
            "sizeBytes": len(PDF),
            "sha256": hashlib.sha256(PDF).hexdigest(),
        },
    )
    existing = harness.job(
        idempotency_key="client:k1", request_hash=digest, input={"documentId": str(original.id)}
    )
    harness.expect_put(PDF)
    harness.expect_delete()  # the duplicate upload's object is discarded
    response = harness.client.post(
        harness.url("/documents"), content=PDF, headers=upload_headers(**{"Idempotency-Key": "k1"})
    )
    assert response.status_code == 202
    assert response.json()["job"]["id"] == str(existing.id)
    assert response.json()["document"]["id"] == str(original.id)
    assert harness.dispatch.await_count == 0 and harness.audits == []


def test_idempotency_conflict(harness):
    harness.job(idempotency_key="client:k1", request_hash="different")
    harness.expect_put(PDF)
    harness.expect_delete()
    response = harness.client.post(
        harness.url("/documents"), content=PDF, headers=upload_headers(**{"Idempotency-Key": "k1"})
    )
    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "idempotency_conflict",
    )


def test_list_get_and_download(harness):
    ready = harness.document()
    pending = harness.document(status="pending")
    listing = harness.client.get(harness.url("/documents?limit=1"), headers=GOOD).json()
    assert len(listing["items"]) == 1 and listing["nextCursor"]
    assert harness.client.get(harness.url("/documents?cursor=@@"), headers=GOOD).status_code == 422
    got = harness.client.get(harness.url(f"/documents/{ready.id}"), headers=GOOD)
    assert got.status_code == 200 and got.json()["id"] == str(ready.id)
    assert harness.client.get(harness.url(f"/documents/{uuid4()}"), headers=GOOD).status_code == 404
    download = harness.client.get(harness.url(f"/documents/{ready.id}/download"), headers=GOOD)
    assert download.status_code == 200
    assert "X-Amz-Expires=60" in download.json()["url"]
    assert "attachment" in download.json()["url"]
    not_ready = harness.client.get(harness.url(f"/documents/{pending.id}/download"), headers=GOOD)
    assert (not_ready.status_code, not_ready.json()["error"]["code"]) == (
        409,
        "document_not_ready",
    )


def test_delete_is_soft_and_idempotent(harness):
    document = harness.document()
    first = harness.client.delete(harness.url(f"/documents/{document.id}"), headers=GOOD)
    assert first.status_code == 202
    assert first.json()["document"]["status"] == "deleted"
    assert first.json()["job"]["kind"] == "document.delete"
    assert document.deleted_at is not None
    second = harness.client.delete(harness.url(f"/documents/{document.id}"), headers=GOOD)
    assert second.status_code == 202
    assert second.json()["job"]["id"] == first.json()["job"]["id"]
    assert harness.dispatch.await_count == 1
    assert [event for event, _ in harness.audits] == ["document.delete"]
    gone = harness.client.get(harness.url(f"/documents/{document.id}/download"), headers=GOOD)
    assert gone.status_code == 404
