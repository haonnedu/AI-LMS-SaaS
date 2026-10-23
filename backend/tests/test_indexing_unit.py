"""Embedding stage (KNOW-06) and the embed/delete job handlers with a fake sync session:
metering, idempotency, failure isolation from activation, and purge replay."""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.documents import Document
from app.models.jobs import BackgroundJob, UsageEvent
from app.models.knowledge import EmbeddingRun
from app.services import embeddings, indexing
from app.services.embeddings import EmbeddingError, EmbeddingResult, LocalHashEmbedder

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


class Rows(list):
    def all(self):
        return list(self)


class FakeSession:
    """Models the chunk table with an embedding triple and the usage ledger."""

    def __init__(self, workspace_id, version_id, texts, *, cap=1000, used=0):
        self.workspace_id, self.version_id = workspace_id, version_id
        self.chunks = [
            SimpleNamespace(
                id=uuid4(),
                document_version_id=version_id,
                text=text,
                token_estimate=400,
                embedding=None,
                embedding_model=None,
                embedding_version=None,
            )
            for text in texts
        ]
        self.cap, self.used = cap, used
        self.added = []
        self.writes = 0
        self.savepoints = 0
        self.fail_writes = False

    def execute(self, statement, params=None):
        sql = str(statement)
        if "SELECT c.id, c.text, c.token_estimate" in sql:
            assert "c.workspace_id = :workspace_id" in sql
            return Rows(
                c
                for c in self.chunks
                if c.document_version_id == params["version_id"]
                and (
                    c.embedding is None
                    or c.embedding_model != params["model"]
                    or c.embedding_version != params["model_version"]
                )
            )
        if sql.lstrip().startswith("UPDATE edu.document_chunks"):
            if self.fail_writes:
                raise RuntimeError("database exploded")
            assert "CAST(:embedding AS vector)" in sql
            by_id = {c.id: c for c in self.chunks}
            for row in params:
                chunk = by_id[row["chunk_id"]]
                assert row["workspace_id"] == self.workspace_id
                assert row["embedding"].startswith("[")
                chunk.embedding = row["embedding"]
                chunk.embedding_model = row["model"]
                chunk.embedding_version = row["model_version"]
                self.writes += 1
            return None
        raise AssertionError(sql)

    def scalar(self, stmt):
        sql = str(stmt)
        if "FROM edu.workspace_quotas" in sql:
            assert "FOR UPDATE" in sql
            return SimpleNamespace(month_cap_units=self.cap)
        assert "sum(edu.usage_events.units)" in sql
        return self.used + sum(e.units for e in self.events())

    def add(self, obj):
        assert isinstance(obj, EmbeddingRun | UsageEvent), type(obj)
        self.added.append(obj)

    def flush(self):
        pass

    @contextmanager
    def begin_nested(self):
        self.savepoints += 1
        yield

    def runs(self):
        return [o for o in self.added if isinstance(o, EmbeddingRun)]

    def events(self):
        return [o for o in self.added if isinstance(o, UsageEvent)]


def stage(db, embedder, job_id=None):
    return indexing.embed_version(
        db,
        workspace_id=db.workspace_id,
        version_id=db.version_id,
        embedder=embedder,
        job_id=job_id,
        now=NOW,
    )


def session(texts=("Mệnh đề là gì", "Tập hợp rỗng"), **kwargs):
    return FakeSession(uuid4(), uuid4(), list(texts), **kwargs)


def test_success_reserves_units_writes_vectors_and_records_run():
    db = session()
    result = stage(db, LocalHashEmbedder())
    (run,) = db.runs()
    assert run.status == "succeeded" and run.finished_at == NOW and run.error_code is None
    assert run.chunk_count == 2 and run.units == 1
    assert (run.model, run.version) == ("local-hash-v1", "1024d.r1")
    assert db.writes == 2
    (reservation,) = db.events()
    assert (reservation.kind, reservation.units, reservation.unit_type) == (
        "reservation",
        1,  # 800 estimated tokens -> 1 unit
        "embedding_ktok",
    )
    assert result["status"] == "succeeded" and result["chunks"] == 2


def test_rerun_with_same_model_is_idempotent_and_new_model_reembeds():
    db = session()
    stage(db, LocalHashEmbedder())
    again = stage(db, LocalHashEmbedder())
    assert again["status"] == "current" and len(db.runs()) == 1 and db.writes == 2
    stage(db, LocalHashEmbedder(revision="2"))  # new version label: stale -> re-embedded
    assert len(db.runs()) == 2 and db.writes == 4
    assert {c.embedding_version for c in db.chunks} == {"1024d.r2"}


class FailingEmbedder(LocalHashEmbedder):
    def embed(self, texts):
        raise EmbeddingError("provider_unavailable", units=3, request_ids=["r1", "r2", "r3"])


def test_provider_failure_marks_run_failed_and_meters_retries():
    db = session()
    result = stage(db, FailingEmbedder(), job_id=uuid4())
    (run,) = db.runs()
    assert (run.status, run.error_code, run.units) == ("failed", "provider_unavailable", 3)
    assert run.provider_request_ids == ["r1", "r2", "r3"]
    assert [(e.kind, e.units) for e in db.events()] == [
        ("reservation", 1),
        ("embedding_overage", 2),  # retries cost more than reserved: still on the ledger
    ]
    assert db.writes == 0 and result["errorCode"] == "provider_unavailable"


def test_quota_exceeded_fails_run_without_calling_provider():
    class Exploding(LocalHashEmbedder):
        def embed(self, texts):
            raise AssertionError("provider must not be called")

    db = session(cap=10, used=10)
    result = stage(db, Exploding())
    assert result["status"] == "failed" and result["errorCode"] == "quota_exceeded"
    assert db.events() == []


def test_mismatched_provider_output_is_rejected():
    class Short(LocalHashEmbedder):
        def embed(self, texts):
            return EmbeddingResult(vectors=[], model=self.model, version=self.version, units=1)

    db = session()
    stage(db, Short())
    assert db.runs()[0].error_code == "provider_bad_response" and db.writes == 0


def test_large_versions_are_embedded_in_batches():
    calls = []

    class Counting(LocalHashEmbedder):
        def embed(self, texts):
            calls.append(len(texts))
            return super().embed(texts)

    db = session([f"đoạn {i}" for i in range(130)])
    stage(db, Counting())
    assert calls == [64, 64, 2] and db.writes == 130


def test_safe_wrapper_isolates_database_errors():
    db = session()
    db.fail_writes = True
    result = indexing.embed_version_safely(
        db, workspace_id=db.workspace_id, version_id=db.version_id,
        embedder=LocalHashEmbedder(), job_id=None, now=NOW,
    )  # fmt: skip
    assert result == {"status": "failed", "errorCode": "embedding_stage_error"}
    assert db.savepoints == 1


# ---------------------------------------------------------------- job handlers


def handler_context(document, kind, db):
    from app.tasks.jobs import HandlerContext

    job = BackgroundJob(
        id=uuid4(),
        workspace_id=document.workspace_id,
        kind=kind,
        input={"documentId": str(document.id)},
    )
    store = SimpleNamespace(deleted=[], delete=lambda key: store.deleted.append(key))
    return HandlerContext(db, job, store, NOW, None, LocalHashEmbedder())


def document(**overrides):
    values = dict(
        id=uuid4(),
        workspace_id=uuid4(),
        object_key="ws/x/doc/y",
        status="uploaded",
        rights_attested=True,
        active_version_id=uuid4(),
    )
    values.update(overrides)
    return Document(**values)


def test_embed_handler_runs_stage_on_active_version(monkeypatch):
    from app.tasks import jobs as tasks

    doc = document()
    seen = {}

    def fake_stage(db, **kwargs):
        seen.update(kwargs)
        return {"status": "succeeded"}

    monkeypatch.setattr(tasks.indexing, "embed_version", fake_stage)
    db = SimpleNamespace(get=lambda *_a, **_k: doc)
    ctx = handler_context(doc, "document.embed", db)
    assert tasks.embed_document(ctx) == {"status": "succeeded"}
    assert seen["version_id"] == doc.active_version_id and seen["job_id"] == ctx.job.id


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"status": "pending"}, "document_not_ready"),
        ({"active_version_id": None}, "document_not_ready"),
        ({"rights_attested": False}, "rights_attestation_required"),
    ],
)
def test_embed_handler_refuses_unready_documents(overrides, code):
    from app.tasks import jobs as tasks

    doc = document(**overrides)
    ctx = handler_context(doc, "document.embed", SimpleNamespace(get=lambda *_a, **_k: doc))
    with pytest.raises(tasks.PermanentJobError, match=code):
        tasks.embed_document(ctx)


def test_embed_handler_skips_deleted_documents():
    from app.tasks import jobs as tasks

    doc = document(status="deleted")
    ctx = handler_context(doc, "document.embed", SimpleNamespace(get=lambda *_a, **_k: doc))
    assert tasks.embed_document(ctx) == {"skipped": True}


class PurgeDb:
    """The purge helper deletes chunks once; a replay finds nothing (idempotent)."""

    def __init__(self, doc, chunks=3):
        self.doc, self.remaining, self.calls = doc, chunks, []

    def get(self, *_a, **_k):
        return self.doc

    def execute(self, statement, params):
        assert "edu.purge_document_chunks(:document_id)" in str(statement)
        self.calls.append(params["document_id"])
        purged, self.remaining = self.remaining, 0
        return SimpleNamespace(scalar_one=lambda: purged)

    def flush(self):
        pass


def test_delete_handler_purges_then_replay_is_a_noop():
    from app.tasks import jobs as tasks

    doc = document(status="deleted")
    db = PurgeDb(doc)
    ctx = handler_context(doc, "document.delete", db)
    assert tasks.delete_document_object(ctx) == {"deleted": True, "purgedChunks": 3}
    assert tasks.delete_document_object(ctx) == {"deleted": True, "purgedChunks": 0}
    assert db.calls == [doc.id, doc.id] and doc.active_version_id is None
    assert ctx.store.deleted == [doc.object_key] * 2


def test_delete_handler_refuses_live_documents():
    from app.tasks import jobs as tasks

    doc = document(status="uploaded")
    ctx = handler_context(doc, "document.delete", PurgeDb(doc))
    with pytest.raises(tasks.PermanentJobError, match="document_not_deleted"):
        tasks.delete_document_object(ctx)
    assert ctx.db.calls == []


def test_embed_job_kind_is_routed_to_ingestion_queue():
    from app.services import jobs as job_service
    from app.tasks import jobs as tasks

    assert job_service.QUEUE_BY_KIND["document.embed"] == "ingestion"
    assert "document.embed" in tasks.HANDLERS
    assert embeddings.MAX_BATCH == 64


def test_ingest_activation_survives_embedding_failure(monkeypatch):
    """KNOW-06: the text version stays active; the embedding outcome is only reported."""
    from app.tasks import jobs as tasks

    doc = document(status="pending")
    version_id = uuid4()
    monkeypatch.setattr(tasks, "_download", lambda ctx, d: b"x")
    monkeypatch.setattr(
        tasks.knowledge,
        "ingest_bytes",
        lambda *a, **k: {"versionId": str(version_id), "versionNo": 1, "unchanged": False},
    )

    def explode(db, **kwargs):
        assert kwargs["version_id"] == version_id
        raise RuntimeError("vector column missing")

    monkeypatch.setattr(tasks.indexing, "embed_version", explode)
    db = FakeSession(doc.workspace_id, version_id, [])
    db.get = lambda *_a, **_k: doc
    ctx = handler_context(doc, "document.ingest", db)
    result = tasks._index(ctx, doc, "ingest")
    assert result["versionNo"] == 1
    assert result["embedding"] == {"status": "failed", "errorCode": "embedding_stage_error"}
