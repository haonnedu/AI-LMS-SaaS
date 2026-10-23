"""Ingest pipeline and version activation state machine (KNOW-02/03) with a fake sync session.

The fake models the two database invariants the pipeline relies on: at most one ``active``
version per document (partial unique index) and chunks only insertable into a ``processing``
version (trigger). A failing transaction rolls back every row and every insert.
"""

import hashlib
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.documents import Document
from app.models.jobs import BackgroundJob
from app.models.knowledge import DocumentChunk, DocumentVersion
from app.services import chunking, knowledge, parsing
from app.services.parsing import DOCX, PDF, TEXT

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
TEXT_V1 = "Chương 1. Mệnh đề. Mệnh đề là một câu khẳng định đúng hoặc sai.".encode()
TEXT_V2 = "Chương 2. Tập hợp. Tập hợp là một khái niệm cơ bản của toán học.".encode()


class FakeDb:
    def __init__(self, *rows):
        self.rows = {row.id: row for row in rows}
        self.versions: list[DocumentVersion] = []
        self.chunks: list[DocumentChunk] = []
        self.pending_chunks: list[DocumentChunk] = []
        self.contexts = []

    # -- session protocol used by execute_job and the services
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @contextmanager
    def begin(self):
        snapshot = {key: dict(vars(row)) for key, row in self.rows.items()}
        versions = {id(v): dict(vars(v)) for v in self.versions}
        lengths = (len(self.versions), len(self.chunks))
        try:
            yield
            self.flush()
        except BaseException:
            for key, values in snapshot.items():
                vars(self.rows[key]).update(values)
            del self.versions[lengths[0] :]
            del self.chunks[lengths[1] :]
            self.pending_chunks.clear()
            for version in self.versions:
                vars(version).update(versions[id(version)])
            raise

    def execute(self, statement, params=None):
        sql = str(statement)
        if "job_actor" in sql:
            job = next(r for r in self.rows.values() if isinstance(r, BackgroundJob))
            actor = SimpleNamespace(
                workspace_id=job.workspace_id, user_id=uuid4(), issuer="https://i/", subject="s"
            )
            return SimpleNamespace(first=lambda: actor)
        assert "set_config" in sql
        self.contexts.append(params)
        return SimpleNamespace(first=lambda: None)

    def get(self, _model, row_id, **_kwargs):
        return self.rows.get(row_id)

    def _document_param(self, stmt) -> UUID:
        params = stmt.compile().params
        return next(v for k, v in params.items() if k.startswith("document_id"))

    def scalar(self, stmt):
        assert "max(" in str(stmt)
        document_id = self._document_param(stmt)
        numbers = [v.version_no for v in self.versions if v.document_id == document_id]
        return max(numbers) if numbers else None

    def scalars(self, stmt):
        document_id = self._document_param(stmt)
        found = [v for v in self.versions if v.document_id == document_id and v.status == "active"]
        return SimpleNamespace(first=lambda: found[0] if found else None)

    def add(self, obj):
        if isinstance(obj, DocumentVersion):
            self.versions.append(obj)
        elif isinstance(obj, DocumentChunk):
            self.pending_chunks.append(obj)
        else:
            raise AssertionError(type(obj))

    def add_all(self, objs):
        for obj in objs:
            self.add(obj)

    def flush(self):
        by_id = {v.id: v for v in self.versions}
        for chunk in self.pending_chunks:
            if by_id[chunk.document_version_id].status != "processing":
                raise IntegrityError("chunk", {}, Exception("version not processing"))
        self.chunks.extend(self.pending_chunks)
        self.pending_chunks.clear()
        active = [v.document_id for v in self.versions if v.status == "active"]
        if len(active) != len(set(active)):
            raise IntegrityError("activate", {}, Exception("uq_document_versions_active"))
        numbers = [(v.document_id, v.version_no) for v in self.versions]
        if len(numbers) != len(set(numbers)):
            raise IntegrityError("version", {}, Exception("uq_document_versions_number"))


class FakeStore:
    def __init__(self, data: bytes):
        self.data = data
        self.downloads = 0

    def head(self, _key):
        return {"ContentLength": len(self.data)}

    def get_bytes(self, _key, *, max_bytes):
        self.downloads += 1
        if len(self.data) > max_bytes:
            from app.services.storage import ObjectTooLarge

            raise ObjectTooLarge()
        return self.data


def make_document(data: bytes, mime=TEXT, status="pending", **overrides) -> Document:
    workspace = overrides.pop("workspace_id", uuid4())
    values = dict(
        id=uuid4(),
        workspace_id=workspace,
        object_key="ws/x/doc/y",
        file_name="tai-lieu.txt",
        mime_type=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).digest(),
        status=status,
        rights_attested=True,
        rights_scope="private",
        active_version_id=None,
    )
    values.update(overrides)
    return Document(**values)


def make_job(document: Document, kind="document.ingest") -> BackgroundJob:
    return BackgroundJob(
        id=uuid4(),
        workspace_id=document.workspace_id,
        requested_by_user_id=uuid4(),
        kind=kind,
        status="queued",
        idempotency_key="system:" + kind,
        request_hash="h",
        attempt=0,
        max_attempts=3,
        cancel_requested=False,
        input={"documentId": str(document.id)},
        created_at=NOW,
        updated_at=NOW,
    )


def run(db: FakeDb, job: BackgroundJob, store: FakeStore) -> str:
    from app.tasks.jobs import execute_job

    return execute_job(
        job.id,
        sessions=lambda: db,
        store=store,
        send=lambda *args, **kwargs: None,
        clock=lambda: NOW,
        max_bytes=1024 * 1024,
    )


def ingest(db: FakeDb, document: Document, data: bytes, mode="ingest"):
    with db.begin():
        return knowledge.ingest_bytes(db, document, data, mode=mode, max_bytes=1 << 20, now=NOW)


def statuses(db: FakeDb):
    return [(v.version_no, v.status) for v in sorted(db.versions, key=lambda v: v.version_no)]


# ---------------------------------------------------------------- service state machine


def test_first_ingest_creates_active_version_with_chunks():
    document = make_document(TEXT_V1)
    db = FakeDb(document)
    result = ingest(db, document, TEXT_V1)
    (version,) = db.versions
    assert statuses(db) == [(1, "active")]
    assert result == {
        "pages": None,
        "versionId": str(version.id),
        "versionNo": 1,
        "chunks": len(db.chunks),
        "unchanged": False,
    }
    assert document.active_version_id == version.id and document.status == "uploaded"
    assert version.activated_at == NOW and version.parser == "text"
    assert version.chunker_version == chunking.CHUNKER_VERSION
    assert version.text_sha256 == hashlib.sha256(TEXT_V1.decode().encode()).digest()
    assert version.char_count == len(TEXT_V1.decode())
    assert {c.document_version_id for c in db.chunks} == {version.id}
    assert all(c.workspace_id == document.workspace_id for c in db.chunks)


def test_new_content_supersedes_previous_in_order():
    document = make_document(TEXT_V1, status="uploaded")
    db = FakeDb(document)
    ingest(db, document, TEXT_V1)
    ingest(db, document, TEXT_V2, mode="reingest")
    assert statuses(db) == [(1, "superseded"), (2, "active")]
    assert document.active_version_id == db.versions[1].id


def test_same_text_is_idempotent_for_ingest_and_reingest():
    document = make_document(TEXT_V1)
    db = FakeDb(document)
    first = ingest(db, document, TEXT_V1)
    chunk_count = len(db.chunks)
    again = ingest(db, document, TEXT_V1)
    assert again["unchanged"] is True and again["versionId"] == first["versionId"]
    same_pipeline = ingest(db, document, TEXT_V1, mode="reingest")
    assert same_pipeline["unchanged"] is True
    assert statuses(db) == [(1, "active")] and len(db.chunks) == chunk_count


def test_reingest_with_newer_chunker_creates_new_version(monkeypatch):
    document = make_document(TEXT_V1, status="uploaded")
    db = FakeDb(document)
    ingest(db, document, TEXT_V1)
    monkeypatch.setattr(chunking, "CHUNKER_VERSION", "2")
    assert ingest(db, document, TEXT_V1)["unchanged"] is True  # plain ingest ignores pipeline
    result = ingest(db, document, TEXT_V1, mode="reingest")
    assert result["unchanged"] is False and result["versionNo"] == 2
    assert statuses(db) == [(1, "superseded"), (2, "active")]
    assert db.versions[1].chunker_version == "2"


def test_rejected_parse_rolls_back_and_keeps_active():
    document = make_document(TEXT_V1, status="uploaded")
    db = FakeDb(document)
    ingest(db, document, TEXT_V1)
    before = (list(db.chunks), document.active_version_id)
    with pytest.raises(knowledge.IngestRejected) as error:
        ingest(db, document, b"bad\x00bytes", mode="reingest")
    assert error.value.code == "invalid_text_encoding" and error.value.suspicious
    assert statuses(db) == [(1, "active")]
    assert (db.chunks, document.active_version_id) == before


def test_unattested_document_is_never_indexed():
    document = make_document(TEXT_V1, rights_attested=False)
    db = FakeDb(document)
    with pytest.raises(knowledge.IngestRejected) as error:
        ingest(db, document, TEXT_V1)
    assert error.value.code == "rights_attestation_required"
    assert db.versions == [] and document.active_version_id is None


def test_activate_requires_processing_and_rights():
    document = make_document(TEXT_V1)
    version = DocumentVersion(id=uuid4(), document_id=document.id, status="failed")
    with pytest.raises(ValueError):
        knowledge.activate(FakeDb(document), document, version, None, NOW)
    document.rights_attested = False
    version.status = "processing"
    with pytest.raises(ValueError):
        knowledge.activate(FakeDb(document), document, version, None, NOW)


def test_activation_without_supersede_would_violate_unique_active():
    """The fake enforces the partial unique index, so skipping supersede is caught."""
    document = make_document(TEXT_V1)
    db = FakeDb(document)
    ingest(db, document, TEXT_V1)
    rogue = DocumentVersion(id=uuid4(), document_id=document.id, version_no=2, status="processing")
    db.add(rogue)
    with pytest.raises(IntegrityError):
        knowledge.activate(db, document, rogue, None, NOW)


def test_failed_version_record_leaves_active_untouched():
    document = make_document(TEXT_V1)
    db = FakeDb(document)
    ingest(db, document, TEXT_V1)
    active = document.active_version_id
    with db.begin():
        failed = knowledge.record_failed_version(
            db, document, code="parse_timeout", parser="text", parser_version="1", now=NOW
        )
    assert statuses(db) == [(1, "active"), (2, "failed")]
    assert failed.error_code == "parse_timeout" and failed.text_sha256 is None
    assert document.active_version_id == active


# ---------------------------------------------------------------- worker handlers end to end


def test_worker_ingest_text_activates_version():
    document = make_document(TEXT_V1)
    job = make_job(document)
    db = FakeDb(document, job)
    store = FakeStore(TEXT_V1)
    assert run(db, job, store) == "succeeded"
    assert job.result["versionNo"] == 1 and job.result["unchanged"] is False
    assert document.status == "uploaded" and statuses(db) == [(1, "active")]
    assert store.downloads == 1


def test_worker_reingest_failure_keeps_previous_active(monkeypatch):
    document = make_document(TEXT_V1, status="uploaded")
    db = FakeDb(document)
    ingest(db, document, TEXT_V1)
    active = document.active_version_id
    job = make_job(document, kind="document.reingest")
    db.rows[job.id] = job

    def broken(_data):
        raise parsing.MalformedDocument("malformed_document")

    monkeypatch.setitem(parsing.PARSERS, TEXT, parsing.Parser("text", "2", broken))
    assert run(db, job, FakeStore(TEXT_V1)) == "failed"
    assert (job.status, job.error_code) == ("failed", "malformed_document")
    assert statuses(db) == [(1, "active"), (2, "failed")]
    assert db.versions[1].parser_version == "2"
    assert document.active_version_id == active and document.status == "uploaded"
    assert all(c.document_version_id == active for c in db.chunks)


def test_worker_pdf_without_parser_is_unsupported_but_downloadable(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", None)
    data = b"%PDF-1.7\n" + b"0" * 32
    document = make_document(data, mime=PDF)
    job = make_job(document)
    db = FakeDb(document, job)
    assert run(db, job, FakeStore(data)) == "failed"
    assert job.error_code == "pdf_parser_unavailable"
    assert statuses(db) == [(1, "failed")]
    assert db.versions[0].error_code == "pdf_parser_unavailable"
    assert document.status == "uploaded" and document.active_version_id is None


def test_worker_malformed_docx_is_quarantined_with_failed_version():
    data = b"PK\x03\x04 truncated"
    document = make_document(data, mime=DOCX)
    job = make_job(document)
    db = FakeDb(document, job)
    assert run(db, job, FakeStore(data)) == "failed"
    assert job.error_code == "malformed_document"
    assert statuses(db) == [(1, "failed")] and document.status == "quarantined"


def test_worker_checksum_mismatch_quarantines_without_version():
    document = make_document(TEXT_V1)
    job = make_job(document)
    db = FakeDb(document, job)
    tampered = TEXT_V1[:-1] + b"!"
    assert run(db, job, FakeStore(tampered)) == "failed"
    assert job.error_code == "object_checksum_mismatch"
    assert db.versions == [] and document.status == "quarantined"


def test_worker_rejects_unattested_document():
    document = make_document(TEXT_V1, rights_attested=False)
    job = make_job(document)
    db = FakeDb(document, job)
    store = FakeStore(TEXT_V1)
    assert run(db, job, store) == "failed"
    assert job.error_code == "rights_attestation_required"
    assert store.downloads == 0 and db.versions == [] and document.status == "quarantined"


def test_worker_reingest_requires_published_document():
    document = make_document(TEXT_V1, status="pending")
    job = make_job(document, kind="document.reingest")
    db = FakeDb(document, job)
    assert run(db, job, FakeStore(TEXT_V1)) == "failed"
    assert job.error_code == "document_not_ready" and document.status == "pending"


def test_worker_reingest_of_deleted_document_is_skipped():
    document = make_document(TEXT_V1, status="deleted")
    job = make_job(document, kind="document.reingest")
    db = FakeDb(document, job)
    assert run(db, job, FakeStore(TEXT_V1)) == "succeeded"
    assert job.result == {"pages": None, "skipped": True}


def test_worker_transient_download_error_retries_without_version():
    document = make_document(TEXT_V1)
    job = make_job(document)
    db = FakeDb(document, job)

    class Flaky(FakeStore):
        def get_bytes(self, _key, *, max_bytes):
            raise ConnectionError("s3 down")

    assert run(db, job, Flaky(TEXT_V1)) == "queued"
    assert job.error_code == "transient_error" and db.versions == []
    assert document.status == "pending"


# ---------------------------------------------------------------- bounded S3 download


def stubbed_store(body: bytes):
    import io

    import boto3
    from botocore.response import StreamingBody
    from botocore.stub import Stubber

    from app.core.config import Settings
    from app.services.storage import ObjectStore

    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test-access",
        aws_secret_access_key="test-secret",
    )
    stub = Stubber(client)
    stub.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(body), len(body))},
        {"Bucket": "eduvia-test", "Key": "ws/a/doc/b"},
    )
    stub.activate()
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+psycopg://eduvia_runtime:x@localhost/eduvia_test",
        auth_issuer="https://identity.example/",
        auth_audience="eduvia-api",
        auth_jwks_url="https://identity.example/jwks",
        s3_bucket="eduvia-test",
    )
    return ObjectStore(settings, client=client)


def test_get_bytes_is_bounded():
    from app.services.storage import ObjectTooLarge

    assert stubbed_store(b"abc").get_bytes("ws/a/doc/b", max_bytes=3) == b"abc"
    with pytest.raises(ObjectTooLarge):
        stubbed_store(b"abcd").get_bytes("ws/a/doc/b", max_bytes=3)
