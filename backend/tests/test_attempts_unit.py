"""Student attempt wrappers without PostgreSQL: error mapping and deterministic race outcomes.

``FakeStudentDb`` emulates the 0011 SECURITY DEFINER functions with the pure mirrors in
``app.services.attempts`` (``decide_save``/``decide_submit``) and the same canonical snapshot,
so the wrappers, their error mapping and the documented race outcomes are exercised end to end.
Row locks are implicit: the fake executes one call at a time, which is exactly the
serialization the attempt row lock provides in PostgreSQL.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from app.services import attempts as service
from app.services import scoring
from app.services.assessment_common import (
    GRACE,
    Conflict,
    Forbidden,
    Invalid,
    NotFound,
    map_db_error,
)

T0 = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)


def db_error(sqlstate):
    class Orig(Exception):
        pass

    orig = Orig("hidden")
    orig.sqlstate = sqlstate
    return DBAPIError("SELECT 1", {}, orig)


# ---- Error mapping --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state,kind,code",
    [
        ("P0002", NotFound, "not_found"),
        ("28000", Forbidden, "account_disabled"),
        ("22023", Invalid, "invalid_request"),
        ("EV010", Conflict, "attempt_expired"),
        ("EV011", Conflict, "idempotency_conflict"),
        ("EV012", Conflict, "assignment_unavailable"),
        ("EV013", Conflict, "attempt_limit_reached"),
        ("EV014", Conflict, "stale_answer"),
        ("EV015", Conflict, "attempt_closed"),
        ("EV016", Invalid, "invalid_option"),
    ],
)
def test_sqlstate_mapping(state, kind, code):
    mapped = map_db_error(db_error(state))
    assert isinstance(mapped, kind) and mapped.code == code
    assert mapped.status == {NotFound: 404, Forbidden: 403, Invalid: 422, Conflict: 409}[kind]
    assert mapped.message and "hidden" not in mapped.message


def test_not_found_is_resource_specific_and_unknown_states_pass_through():
    mapped = map_db_error(db_error("P0002"), not_found=("attempt_not_found", "x"))
    assert isinstance(mapped, NotFound) and mapped.code == "attempt_not_found"
    original = db_error("XX000")
    assert map_db_error(original) is original
    # Mapped instances are fresh objects: a shared template is never mutated or re-raised.
    assert map_db_error(db_error("EV010")) is not map_db_error(db_error("EV010"))


# ---- Pure rules -----------------------------------------------------------------------------


def save(stored=None, status="in_progress", deadline=T0 + timedelta(minutes=10), now=T0, **kw):
    values = {"selected_key": "A", "expected_revision": 0, "client_sequence": 1} | kw
    return service.decide_save(
        status=status, deadline_at=deadline, now=now, stored=stored, **values
    )


def test_save_rules():
    stored = service.StoredAnswer("B", answer_revision=2, client_sequence=5)
    assert save() == "write"
    assert save(expected_revision=1) == "EV014"
    assert save(stored, expected_revision=2, client_sequence=6) == "write"
    assert save(stored, expected_revision=2, client_sequence=5) == "EV014"  # reordered
    assert save(stored, expected_revision=1, client_sequence=6) == "EV014"  # stale revision
    assert save(stored, selected_key="B", expected_revision=1, client_sequence=5) == "ack"
    assert save(stored, selected_key="C", expected_revision=1, client_sequence=5) == "EV014"
    assert save(status="submitted") == "EV015"
    assert save(deadline=None, now=T0 + timedelta(days=30)) == "write"  # untimed


def test_grace_boundary_is_inclusive():
    deadline = T0
    assert save(deadline=deadline, now=deadline + GRACE) == "write"
    assert save(deadline=deadline, now=deadline + GRACE + timedelta(microseconds=1)) == "EV010"


def test_submit_rules():
    kw = {"stored_key": None, "stored_hash": None, "key": "k", "digest": "h"}
    late = T0 + GRACE + timedelta(seconds=1)
    assert service.decide_submit(status="in_progress", deadline_at=T0, now=T0, **kw) == "student"
    assert service.decide_submit(status="in_progress", deadline_at=T0, now=late, **kw) == (
        "deadline"
    )
    assert service.decide_submit(status="void", deadline_at=None, now=T0, **kw) == "EV015"
    replay = kw | {"stored_key": "k", "stored_hash": "h"}
    assert service.decide_submit(status="graded", deadline_at=None, now=T0, **replay) == "replay"
    conflict = replay | {"digest": "other"}
    assert service.decide_submit(status="submitted", deadline_at=None, now=T0, **conflict) == (
        "EV011"
    )
    # Finalized by the sweeper (no key): any later submit is a no-op replay.
    assert service.decide_submit(status="submitted", deadline_at=T0, now=late, **kw) == "replay"


def test_effective_deadline_is_the_earliest_bound():
    started = T0
    assert service.effective_deadline(started, None, None) is None
    assert service.effective_deadline(started, T0 + timedelta(hours=1), None) == T0 + timedelta(
        hours=1
    )
    assert service.effective_deadline(started, None, 600) == T0 + timedelta(seconds=600)
    assert service.effective_deadline(started, T0 + timedelta(minutes=5), 600) == T0 + timedelta(
        minutes=5
    )


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, "open"),
        ({"in_progress": True, "status": "closed"}, "resume"),
        ({"opens_at": T0 + timedelta(minutes=1)}, "not_open_yet"),
        ({"closes_at": T0}, "closed"),
        ({"closes_at": T0, "attempts_used": 1}, "done"),
        ({"status": "closed"}, "closed"),
        ({"class_active": False}, "closed"),
        ({"attempts_used": 1}, "limit_reached"),
        ({"attempts_used": 1, "max_attempts": 2}, "open"),
    ],
)
def test_start_availability(overrides, expected):
    values = {
        "status": "published",
        "class_active": True,
        "opens_at": T0 - timedelta(hours=1),
        "closes_at": T0 + timedelta(hours=1),
        "now": T0,
        "attempts_used": 0,
        "max_attempts": 1,
        "in_progress": False,
    } | overrides
    assert service.start_availability(**values) == expected


# ---- Fake definer functions -----------------------------------------------------------------


class Rows(list):
    def all(self):
        return list(self)


class FakeStudentDb:
    """One student's view of the 0011 functions, driven by an adjustable clock."""

    def __init__(self, deadline_minutes=10):
        self.now = T0
        self.student = uuid4()
        self.attempt = SimpleNamespace(
            id=uuid4(),
            owner=self.student,
            status="in_progress",
            started_at=T0,
            deadline_at=T0 + timedelta(minutes=deadline_minutes),
            submitted_at=None,
            reason=None,
            key=None,
            digest=None,
            snapshot=None,
        )
        self.items = [uuid4(), uuid4()]
        self.answers: dict = {}
        self.jobs: list = []
        self.calls: list[str] = []

    # -- helpers --
    def _raise(self, state):
        raise db_error(state)

    def _finalize(self, reason):
        att = self.attempt
        if att.status != "in_progress":
            return None
        att.status = "submitted"
        att.reason = reason
        att.submitted_at = (
            min(att.deadline_at, self.now) if reason == "deadline" and att.deadline_at else self.now
        )
        att.snapshot = scoring.snapshot_sha256(
            (item, answer.selected_key) for item, answer in self.answers.items()
        )
        job = uuid4()
        self.jobs.append(job)
        return job

    def _own(self, attempt_id):
        if attempt_id != self.attempt.id:
            self._raise("P0002")

    # -- functions --
    def save(self, p):
        self._own(p["attempt"])
        if p["item"] not in self.items:
            self._raise("P0002")
        stored = self.answers.get(p["item"])
        outcome = service.decide_save(
            status=self.attempt.status,
            deadline_at=self.attempt.deadline_at,
            now=self.now,
            stored=stored,
            selected_key=p["key"],
            expected_revision=p["expected"],
            client_sequence=p["sequence"],
        )
        if outcome.startswith("EV"):
            self._raise(outcome)
        if outcome == "write":
            revision = (stored.answer_revision if stored else 0) + 1
            self.answers[p["item"]] = service.StoredAnswer(p["key"], revision, p["sequence"])
        answer = self.answers[p["item"]]
        return Rows(
            [
                SimpleNamespace(
                    out_answer_revision=answer.answer_revision,
                    out_saved_at=self.now,
                    out_server_now=self.now,
                )
            ]
        )

    def submit(self, p):
        self._own(p["attempt"])
        att = self.attempt
        outcome = service.decide_submit(
            status=att.status,
            deadline_at=att.deadline_at,
            now=self.now,
            stored_key=att.key,
            stored_hash=att.digest,
            key=p["key"],
            digest=p["hash"],
        )
        if outcome.startswith("EV"):
            self._raise(outcome)
        job = None
        if outcome in ("student", "deadline"):
            att.key, att.digest = p["key"], p["hash"]
            job = self._finalize(outcome)
        return Rows(
            [
                SimpleNamespace(
                    out_status=att.status,
                    out_submitted_at=att.submitted_at,
                    out_snapshot_sha256=att.snapshot,
                    out_submission_reason=att.reason,
                    out_job_id=job,
                    out_replayed=outcome == "replay",
                )
            ]
        )

    def expire(self, p):
        effective = min(p["now"], self.now)  # a future time can never expire early
        att = self.attempt
        if (
            att.status == "in_progress"
            and att.deadline_at is not None
            and att.deadline_at + GRACE < effective
        ):
            job = self._finalize("deadline")
            return Rows([(att.id, uuid4(), job)])
        return Rows()

    def dispatch(self, sql, params):
        self.calls.append(sql)
        if "student_save_answer" in sql:
            return self.save(params)
        if "student_submit" in sql:
            return self.submit(params)
        if "expire_attempts" in sql:
            return self.expire(params)
        raise AssertionError(sql)


class AsyncFacade:
    def __init__(self, fake):
        self.fake = fake

    async def execute(self, stmt, params=None):
        return self.fake.dispatch(str(stmt), params)


class SyncFacade:
    def __init__(self, fake):
        self.fake = fake

    def execute(self, stmt, params=None):
        return self.fake.dispatch(str(stmt), params)


async def put(fake, item, key, expected, sequence):
    return await service.save_answer(
        AsyncFacade(fake),
        fake.attempt.id,
        item,
        selected_key=key,
        expected_revision=expected,
        client_sequence=sequence,
    )


# ---- Race outcomes --------------------------------------------------------------------------


async def test_stale_autosave_never_overwrites_a_newer_answer():
    fake = FakeStudentDb()
    item = fake.items[0]
    assert (await put(fake, item, "A", 0, 1)).answer_revision == 1
    assert (await put(fake, item, "C", 1, 3)).answer_revision == 2
    with pytest.raises(Conflict) as caught:  # delayed request #2 arrives last
        await put(fake, item, "B", 1, 2)
    assert caught.value.code == "stale_answer"
    assert fake.answers[item].selected_key == "C"
    # An exact retry of the committed write is acknowledged, not re-applied.
    assert (await put(fake, item, "C", 1, 3)).answer_revision == 2
    assert fake.answers[item].answer_revision == 2


async def test_clearing_an_answer_is_a_recorded_blank():
    fake = FakeStudentDb()
    item = fake.items[1]
    await put(fake, item, "D", 0, 1)
    await put(fake, item, None, 1, 2)
    submission = await service.submit(AsyncFacade(fake), fake.attempt.id, "client:k")
    expected = scoring.snapshot_sha256([(item, None)])
    assert submission.snapshot_sha256 == expected.hex()


async def test_submit_twice_with_same_key_returns_the_same_snapshot():
    fake = FakeStudentDb()
    await put(fake, fake.items[0], "A", 0, 1)
    db = AsyncFacade(fake)
    first = await service.submit(db, fake.attempt.id, "client:k1")
    second = await service.submit(db, fake.attempt.id, "client:k1")
    other_key = await service.submit(db, fake.attempt.id, "client:k2")
    assert first.replayed is False and second.replayed is other_key.replayed is True
    assert first.snapshot_sha256 == second.snapshot_sha256 == other_key.snapshot_sha256
    assert first.job_id is not None and second.job_id is None and len(fake.jobs) == 1
    assert first.submission_reason == "student" and first.submitted_at == T0


async def test_same_submit_key_with_different_request_conflicts(monkeypatch):
    fake = FakeStudentDb()
    db = AsyncFacade(fake)
    await service.submit(db, fake.attempt.id, "client:k1")
    monkeypatch.setattr(service, "submit_request_hash", lambda attempt_id: "different")
    with pytest.raises(Conflict) as caught:
        await service.submit(db, fake.attempt.id, "client:k1")
    assert caught.value.code == "idempotency_conflict"


async def test_autosave_after_expiry_or_submission_is_rejected():
    fake = FakeStudentDb(deadline_minutes=10)
    await put(fake, fake.items[0], "A", 0, 1)
    fake.now = T0 + timedelta(minutes=10) + GRACE  # still inside the transport grace
    assert (await put(fake, fake.items[0], "B", 1, 2)).answer_revision == 2
    fake.now += timedelta(milliseconds=1)
    with pytest.raises(Conflict) as caught:
        await put(fake, fake.items[1], "C", 0, 3)
    assert caught.value.code == "attempt_expired"
    assert fake.items[1] not in fake.answers
    await service.submit(AsyncFacade(fake), fake.attempt.id, "client:k")
    with pytest.raises(Conflict) as caught:
        await put(fake, fake.items[1], "C", 0, 4)
    assert caught.value.code == "attempt_closed"


async def test_expiry_first_then_submit_is_a_noop_with_the_same_snapshot():
    fake = FakeStudentDb(deadline_minutes=10)
    await put(fake, fake.items[0], "A", 0, 1)
    fake.now = T0 + timedelta(minutes=11)
    expired = service.expire_due(SyncFacade(fake), fake.now)
    assert [e.attempt_id for e in expired] == [fake.attempt.id] and expired[0].job_id
    assert fake.attempt.reason == "deadline"
    assert fake.attempt.submitted_at == T0 + timedelta(minutes=10)  # the deadline, not "now"
    late = await service.submit(AsyncFacade(fake), fake.attempt.id, "client:k")
    assert late.replayed is True and late.job_id is None
    assert late.submission_reason == "deadline"
    assert late.snapshot_sha256 == fake.attempt.snapshot.hex()
    assert len(fake.jobs) == 1


async def test_submit_first_then_expiry_finds_nothing():
    fake = FakeStudentDb(deadline_minutes=10)
    first = await service.submit(AsyncFacade(fake), fake.attempt.id, "client:k")
    fake.now = T0 + timedelta(hours=1)
    assert service.expire_due(SyncFacade(fake), fake.now) == []
    assert fake.attempt.reason == "student" and len(fake.jobs) == 1
    assert fake.attempt.snapshot.hex() == first.snapshot_sha256


async def test_late_submit_before_sweep_finalizes_as_deadline():
    fake = FakeStudentDb(deadline_minutes=10)
    await put(fake, fake.items[0], "A", 0, 1)
    fake.now = T0 + timedelta(minutes=30)
    submission = await service.submit(AsyncFacade(fake), fake.attempt.id, "client:k")
    assert submission.replayed is False and submission.submission_reason == "deadline"
    assert submission.submitted_at == T0 + timedelta(minutes=10)


async def test_sweeper_cannot_be_driven_by_a_future_clock():
    fake = FakeStudentDb(deadline_minutes=10)
    assert service.expire_due(SyncFacade(fake), T0 + timedelta(days=1)) == []
    assert fake.attempt.status == "in_progress"


async def test_another_students_attempt_is_not_found():
    fake = FakeStudentDb()
    with pytest.raises(NotFound) as caught:
        await service.save_answer(
            AsyncFacade(fake),
            uuid4(),
            fake.items[0],
            selected_key="A",
            expected_revision=0,
            client_sequence=1,
        )
    assert caught.value.code == "attempt_not_found"


# ---- Typed wrappers -------------------------------------------------------------------------


class ScriptedDb:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return Rows(result)


async def test_start_attempt_wrapper_passes_a_server_derived_hash():
    assignment, attempt = uuid4(), uuid4()
    row = SimpleNamespace(
        out_attempt_id=attempt,
        out_created=True,
        out_status="in_progress",
        out_attempt_no=1,
        out_started_at=T0,
        out_deadline_at=T0 + timedelta(minutes=15),
        out_server_now=T0,
    )
    db = ScriptedDb([row])
    started = await service.start_attempt(db, assignment, "client:abc")
    assert started.created and started.attempt_id == attempt
    sql, params = db.calls[0]
    assert "edu.student_start_attempt" in sql
    assert params == {
        "assignment": assignment,
        "key": "client:abc",
        "hash": service.start_request_hash(assignment),
    }


@pytest.mark.parametrize(
    "state,code",
    [
        ("P0002", "assignment_not_found"),
        ("EV012", "assignment_unavailable"),
        ("EV013", "attempt_limit_reached"),
        ("EV011", "idempotency_conflict"),
    ],
)
async def test_start_attempt_errors(state, code):
    with pytest.raises(Exception) as caught:
        await service.start_attempt(ScriptedDb(db_error(state)), uuid4(), "client:k")
    assert caught.value.code == code


async def test_unknown_database_errors_propagate():
    with pytest.raises(DBAPIError):
        await service.start_attempt(ScriptedDb(db_error("40001")), uuid4(), "client:k")


async def test_detail_of_invisible_assignment_is_404():
    with pytest.raises(NotFound) as caught:
        await service.assignment_detail(ScriptedDb([]), uuid4())
    assert caught.value.code == "assignment_not_found"
    with pytest.raises(NotFound):
        await service.attempt_view(ScriptedDb([]), uuid4())


def test_result_types_have_no_key_fields():
    from dataclasses import fields

    for kind in (
        service.StudentAssignment,
        service.StartedAttempt,
        service.AttemptItem,
        service.AttemptView,
        service.SavedAnswer,
        service.Submission,
    ):
        names = {f.name for f in fields(kind)}
        assert not names & {"correct_key", "explanation", "key", "answer_key"}, kind
