"""Job state machine, idempotency and sweeper logic without PostgreSQL."""

from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.api.identity import ApiError
from app.models.jobs import JOB_STATUSES, BackgroundJob
from app.services import jobs

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
EDGES = {
    ("queued", "running"),
    ("queued", "cancelled"),
    ("running", "succeeded"),
    ("running", "failed"),
    ("running", "queued"),
    ("running", "cancelled"),
    ("failed", "queued"),
}


def make_job(status="queued", **overrides) -> BackgroundJob:
    values = dict(
        id=uuid4(),
        workspace_id=uuid4(),
        requested_by_user_id=uuid4(),
        kind="document.ingest",
        status=status,
        idempotency_key="client:k",
        request_hash="h",
        attempt=0,
        max_attempts=3,
        cancel_requested=False,
        input={},
        created_at=NOW,
        updated_at=NOW,
    )
    values.update(overrides)
    return BackgroundJob(**values)


@pytest.mark.parametrize("source", JOB_STATUSES)
@pytest.mark.parametrize("target", JOB_STATUSES)
def test_transition_matrix(source, target):
    job = make_job(source)
    if (source, target) in EDGES:
        jobs.transition(job, target, now=NOW)
        assert job.status == target
        assert (job.finished_at is not None) == (target in jobs.TERMINAL)
    else:
        with pytest.raises(jobs.InvalidTransition):
            jobs.transition(job, target, now=NOW)
        assert job.status == source


def test_request_hash_is_canonical():
    a = jobs.request_hash("document.upload", {"a": 1, "b": [1, 2]})
    assert a == jobs.request_hash("document.upload", {"b": [1, 2], "a": 1})
    assert a != jobs.request_hash("document.upload", {"a": 2, "b": [1, 2]})
    assert a != jobs.request_hash("document.delete", {"a": 1, "b": [1, 2]})


@pytest.mark.parametrize("raw", ["", "x" * 129, "khóa", "a\nb"])
def test_client_key_validation(raw):
    with pytest.raises(ApiError) as error:
        jobs.client_idempotency_key(raw)
    assert error.value.code == "invalid_idempotency_key"


def test_client_keys_are_namespaced():
    assert jobs.client_idempotency_key("abc") == "client:abc"
    assert jobs.client_idempotency_key(None).startswith("client:")
    assert jobs.client_idempotency_key(None) != jobs.client_idempotency_key(None)


class FakeAsyncDb:
    def __init__(self, found=(), conflict=False):
        self.found = list(found)
        self.conflict = conflict
        self.added = []

    async def scalar(self, _stmt):
        return self.found.pop(0) if self.found else None

    @asynccontextmanager
    async def begin_nested(self):
        yield

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        if self.conflict:
            raise IntegrityError("insert", {}, Exception("duplicate"))


SCOPE = SimpleNamespace(user=SimpleNamespace(id=uuid4()), workspace=SimpleNamespace(id=uuid4()))


async def test_enqueue_creates_queued_job():
    db = FakeAsyncDb()
    job, created = await jobs.enqueue_job(db, SCOPE, "document.ingest", {"x": 1}, "client:k")
    assert created and db.added == [job]
    assert (job.status, job.attempt, job.workspace_id) == ("queued", 0, SCOPE.workspace.id)
    assert job.request_hash == jobs.request_hash("document.ingest", {"x": 1})


async def test_enqueue_duplicate_same_request_returns_existing():
    existing = make_job(request_hash=jobs.request_hash("document.ingest", {"x": 1}))
    db = FakeAsyncDb(found=[existing])
    job, created = await jobs.enqueue_job(db, SCOPE, "document.ingest", {"x": 1}, "client:k")
    assert job is existing and not created and db.added == []


async def test_enqueue_duplicate_different_request_conflicts():
    db = FakeAsyncDb(found=[make_job(request_hash="other")])
    with pytest.raises(ApiError) as error:
        await jobs.enqueue_job(db, SCOPE, "document.ingest", {"x": 1}, "client:k")
    assert (error.value.status, error.value.code) == (409, "idempotency_conflict")


async def test_enqueue_race_resolved_by_unique_constraint():
    winner = make_job(request_hash=jobs.request_hash("document.ingest", {"x": 1}))
    db = FakeAsyncDb(found=[None, winner], conflict=True)
    job, created = await jobs.enqueue_job(db, SCOPE, "document.ingest", {"x": 1}, "client:k")
    assert job is winner and not created


class FakeSyncDb:
    def __init__(self, *rows):
        self.rows = {row.id: row for row in rows}
        self.flushes = 0

    def get(self, _model, job_id, **_kwargs):
        return self.rows.get(job_id)

    def scalars(self, _query):
        return list(self.rows.values())

    def flush(self):
        self.flushes += 1


def test_claim_complete_is_idempotent_per_attempt():
    job = make_job()
    db = FakeSyncDb(job)
    attempt = jobs.claim_job(db, job.id, NOW)
    assert attempt == 1 and job.status == "running"
    assert job.lease_expires_at == NOW + jobs.LEASE
    assert jobs.claim_job(db, job.id, NOW) is None  # live lease: redelivery does not run
    assert jobs.complete_job(db, job.id, attempt, {"pages": None}, NOW)
    assert (job.status, job.result, job.lease_expires_at) == ("succeeded", {"pages": None}, None)
    assert not jobs.complete_job(db, job.id, attempt, {"pages": 1}, NOW)
    assert job.result == {"pages": None}


def test_stale_attempt_cannot_write():
    job = make_job("running", attempt=2, lease_expires_at=NOW + timedelta(minutes=1))
    db = FakeSyncDb(job)
    assert not jobs.complete_job(db, job.id, 1, {"stale": True}, NOW)
    assert jobs.fail_job(db, job.id, 1, "boom", retryable=True, now=NOW) is None
    assert job.status == "running" and job.result is None


def test_expired_lease_is_reclaimed_with_next_attempt():
    job = make_job("running", attempt=1, lease_expires_at=NOW - timedelta(seconds=1))
    assert jobs.claim_job(FakeSyncDb(job), job.id, NOW) == 2
    assert job.status == "running" and job.lease_expires_at > NOW


def test_fail_retries_until_max_attempts():
    job = make_job()
    db = FakeSyncDb(job)
    outcomes = []
    for _ in range(3):
        attempt = jobs.claim_job(db, job.id, NOW)
        outcomes.append(jobs.fail_job(db, job.id, attempt, "transient", retryable=True, now=NOW))
    assert outcomes == ["queued", "queued", "failed"]
    assert job.error_code == "transient" and job.finished_at == NOW


def test_permanent_failure_does_not_retry():
    job = make_job()
    db = FakeSyncDb(job)
    attempt = jobs.claim_job(db, job.id, NOW)
    assert jobs.fail_job(db, job.id, attempt, "object_missing", retryable=False) == "failed"


def test_cancel_requested_is_honoured_at_claim_and_between_stages():
    queued = make_job(cancel_requested=True)
    assert jobs.claim_job(FakeSyncDb(queued), queued.id, NOW) is None
    assert queued.status == "cancelled"
    running = make_job()
    db = FakeSyncDb(running)
    attempt = jobs.claim_job(db, running.id, NOW)
    assert jobs.request_cancel(running, NOW) and running.status == "running"
    assert jobs.cancel_running(db, running.id, attempt, NOW)
    assert running.status == "cancelled"


def test_cancel_and_retry_api_rules():
    queued = make_job()
    assert jobs.request_cancel(queued, NOW) and queued.status == "cancelled"
    assert not jobs.request_cancel(queued, NOW)  # repeat is a no-op
    with pytest.raises(ApiError) as error:
        jobs.request_cancel(make_job("succeeded"), NOW)
    assert error.value.code == "job_not_cancellable"
    failed = make_job("failed", attempt=3, error_code="transient")
    assert jobs.request_retry(failed, NOW)
    assert (failed.status, failed.attempt, failed.error_code) == ("queued", 0, None)
    assert not jobs.request_retry(failed, NOW)  # already re-queued: no duplicate action
    with pytest.raises(ApiError) as error:
        jobs.request_retry(make_job("cancelled"), NOW)
    assert error.value.code == "job_not_retryable"


@pytest.mark.parametrize(
    "job,expected",
    [
        (make_job("running", attempt=1, lease_expires_at=NOW - timedelta(seconds=1)), "requeued"),
        (make_job("running", attempt=3, lease_expires_at=NOW - timedelta(seconds=1)), "failed"),
        (
            make_job(
                "running",
                attempt=1,
                cancel_requested=True,
                lease_expires_at=NOW - timedelta(seconds=1),
            ),
            "cancelled",
        ),
        (make_job("running", attempt=1, lease_expires_at=NOW + timedelta(seconds=1)), None),
        (make_job("queued", updated_at=NOW - timedelta(minutes=11)), "redispatch"),
        (make_job("queued", updated_at=NOW - timedelta(minutes=1)), None),
        (make_job("succeeded", updated_at=NOW - timedelta(days=1)), None),
    ],
)
def test_decide_sweep(job, expected):
    assert jobs.decide_sweep(job, NOW) == expected


def test_sweep_overdue_applies_outcomes():
    expired = make_job("running", attempt=1, lease_expires_at=NOW - timedelta(minutes=1))
    exhausted = make_job("running", attempt=3, lease_expires_at=NOW - timedelta(minutes=1))
    stale = make_job("queued", updated_at=NOW - timedelta(hours=1))
    healthy = make_job("running", attempt=1, lease_expires_at=NOW + timedelta(minutes=1))
    outcomes = jobs.sweep_overdue(FakeSyncDb(expired, exhausted, stale, healthy), NOW)
    assert {(o.job_id, o.action) for o in outcomes} == {
        (expired.id, "requeued"),
        (exhausted.id, "failed"),
        (stale.id, "redispatch"),
    }
    assert expired.status == "queued" and expired.lease_expires_at is None
    assert exhausted.status == "failed" and exhausted.error_code == "lease_expired"
    assert stale.updated_at == NOW and healthy.status == "running"


async def test_dispatch_failure_is_not_fatal(monkeypatch):
    def broken(*_args, **_kwargs):
        raise ConnectionError("broker down")

    monkeypatch.setattr(jobs, "send_job", broken)
    assert await jobs.dispatch_job(make_job()) is False


# ---- worker execution (app.tasks.jobs) with a fake sync session ----


class FakeWorkerDb:
    def __init__(self, rows, actor=True):
        self.rows = {row.id: row for row in rows}
        self.actor = actor
        self.contexts = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @contextmanager
    def begin(self):
        snapshot = {key: dict(vars(row)) for key, row in self.rows.items()}
        try:
            yield
        except BaseException:
            for key, values in snapshot.items():  # rollback
                vars(self.rows[key]).update(values)
            raise

    def execute(self, statement, params=None):
        sql = str(statement)
        if "job_actor" in sql:
            row = SimpleNamespace(
                workspace_id=uuid4(), user_id=uuid4(), issuer="https://i/", subject="s"
            )
            return SimpleNamespace(first=lambda: row if self.actor else None)
        if "purge_document_chunks" in sql:  # KNOW-09 deletion helper (0008)
            self.purged = getattr(self, "purged", []) + [params["document_id"]]
            return SimpleNamespace(scalar_one=lambda: 0)
        assert "set_config" in sql and set(params) == {
            "issuer",
            "subject",
            "user_id",
            "workspace_id",
        }
        self.contexts.append(params)
        return SimpleNamespace(first=lambda: None)

    def get(self, _model, row_id, **_kwargs):
        return self.rows.get(row_id)

    def flush(self):
        pass


class FakeStore:
    def __init__(self, length=10):
        self.length, self.deleted = length, []

    def head(self, _key):
        return None if self.length is None else {"ContentLength": self.length}

    def delete(self, key):
        self.deleted.append(key)


def worker_fixture(kind="document.ingest", doc_status="pending", **job_overrides):
    from app.models.documents import Document

    workspace = uuid4()
    document = Document(
        id=uuid4(),
        workspace_id=workspace,
        object_key="ws/x/doc/y",
        size_bytes=10,
        status=doc_status,
    )
    job = make_job(
        kind=kind, workspace_id=workspace, input={"documentId": str(document.id)}, **job_overrides
    )
    return job, document, FakeWorkerDb([job, document])


def run_worker(db, job, store, sent=None):
    from app.tasks.jobs import execute_job

    return execute_job(
        job.id,
        sessions=lambda: db,
        store=store,
        send=lambda *args, **kwargs: (sent if sent is not None else []).append((args, kwargs)),
        clock=lambda: NOW,
    )


def test_worker_ingest_success_and_duplicate_delivery():
    job, document, db = worker_fixture()
    assert run_worker(db, job, FakeStore()) == "succeeded"
    assert (job.status, job.result, document.status) == ("succeeded", {"pages": None}, "uploaded")
    assert len(db.contexts) == 2  # context set in each transaction, never reused
    assert run_worker(db, job, FakeStore()) == "not_claimed"


def test_worker_missing_object_fails_permanently_and_quarantines():
    job, document, db = worker_fixture()
    assert run_worker(db, job, FakeStore(length=None)) == "failed"
    assert (job.status, job.error_code, document.status) == (
        "failed",
        "object_missing",
        "quarantined",
    )


def test_worker_transient_error_requeues_and_redispatches():
    job, document, db = worker_fixture()

    class Flaky(FakeStore):
        def head(self, _key):
            raise ConnectionError("s3 down")

    sent = []
    assert run_worker(db, job, Flaky(), sent) == "queued"
    assert (job.status, job.attempt, job.error_code) == ("queued", 1, "transient_error")
    assert document.status == "pending"
    assert sent and sent[0][0] == (job.id, "document.ingest")


def test_worker_honours_cancel_and_missing_actor():
    job, _, db = worker_fixture(cancel_requested=True)
    assert run_worker(db, job, FakeStore()) == "not_claimed" and job.status == "cancelled"
    job, _, db = worker_fixture()
    db.actor = False
    assert run_worker(db, job, FakeStore()) == "skipped" and job.status == "queued"


def test_worker_delete_handler_is_idempotent():
    job, document, db = worker_fixture(kind="document.delete", doc_status="deleted")
    store = FakeStore()
    assert run_worker(db, job, store) == "succeeded"
    assert store.deleted == [document.object_key]
    assert job.result == {"deleted": True, "purgedChunks": 0}
    assert db.purged == [document.id] and document.active_version_id is None
