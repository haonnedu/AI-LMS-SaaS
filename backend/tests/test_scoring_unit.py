"""Pure single-choice scoring, snapshot/run keys and the ``attempt.grade`` job (no database)."""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.elements import TextClause

from app.services import jobs as job_service
from app.services import scoring
from app.services.scoring import ScoringItem, q2, score_single_choice
from app.tasks import jobs as tasks

NOW = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)
CHOICES = frozenset("ABCD")


def ids(n):
    return sorted(uuid4() for _ in range(n))


# ---- Pure scoring ---------------------------------------------------------------------------


def test_fixed_precision_fixture():
    a, b, c, d = ids(4)
    items = [
        ScoringItem(a, Decimal("0.25"), "A", CHOICES),
        ScoringItem(b, Decimal("0.25"), "B", CHOICES),
        ScoringItem(c, Decimal("0.5"), "C", CHOICES),
        ScoringItem(d, Decimal("1"), "D", CHOICES),
    ]
    result = score_single_choice(items, {a: "A", b: "C", c: "C", d: None})
    assert result.raw_score == Decimal("0.75") and str(result.raw_score) == "0.75"
    assert result.max_score == Decimal("2.00") and str(result.max_score) == "2.00"
    assert [o.reason for o in result.items] == ["correct", "incorrect", "correct", "blank"]
    assert [str(o.awarded_points) for o in result.items] == ["0.25", "0.00", "0.50", "0.00"]
    assert result.algorithm_version == "sc-1"


def test_tenths_sum_exactly_without_float_drift():
    items = [ScoringItem(i, Decimal("0.1"), "A") for i in ids(3)]
    result = score_single_choice(items, {item.item_id: "A" for item in items})
    assert result.raw_score == Decimal("0.30") and result.max_score == Decimal("0.30")
    assert 0.1 + 0.1 + 0.1 != 0.3  # the float trap this avoids


def test_blank_and_missing_answers_score_zero_but_are_recorded():
    a, b = ids(2)
    items = [ScoringItem(a, Decimal(1), "A"), ScoringItem(b, Decimal(1), "B")]
    result = score_single_choice(items, {a: "  "})
    for outcome in result.items:
        assert outcome.reason == "blank" and outcome.answer_source == "blank"
        assert outcome.awarded_points == Decimal("0.00")
        assert outcome.effective_response == {"selectedKey": None}
    assert result.count("blank") == 2


def test_invalid_option_scores_zero_and_is_never_negative():
    a, b = ids(2)
    items = [ScoringItem(a, Decimal(2), "A", CHOICES), ScoringItem(b, Decimal(2), "B", CHOICES)]
    result = score_single_choice(items, {a: "Z", b: "C"})
    assert [o.reason for o in result.items] == ["invalid_option", "incorrect"]
    assert result.raw_score == Decimal("0.00") >= 0
    assert all(o.awarded_points >= 0 for o in result.items)


def test_padded_char_key_and_unknown_items():
    a = uuid4()
    result = score_single_choice([ScoringItem(a, Decimal(1), "A ")], {a: "A", uuid4(): "B"})
    assert result.raw_score == Decimal("1.00") and len(result.items) == 1


@pytest.mark.parametrize(
    "items",
    [
        [],
        [ScoringItem(UUID(int=1), Decimal(0), "A")],
        [ScoringItem(UUID(int=1), Decimal(-1), "A")],
        [ScoringItem(UUID(int=1), Decimal(1), None)],
        [ScoringItem(UUID(int=1), Decimal(1), "A"), ScoringItem(UUID(int=1), Decimal(1), "B")],
    ],
)
def test_unusable_exam_is_rejected_not_scored_zero(items):
    with pytest.raises(ValueError):
        score_single_choice(items, {})


def test_quantize_rounds_half_up():
    assert q2("0.125") == Decimal("0.13") and q2(1) == Decimal("1.00")


# ---- Snapshot and run key -------------------------------------------------------------------


def test_snapshot_is_order_independent_and_matches_sql_canonical_form():
    a, b = ids(2)
    one = scoring.snapshot_sha256([(b, None), (a, "C")])
    two = scoring.snapshot_sha256([(a, "C"), (b, None)])
    assert one == two == hashlib.sha256(f"{a}:C\n{b}:".encode()).digest()
    assert scoring.snapshot_sha256([]) == hashlib.sha256(b"").digest()
    assert scoring.snapshot_sha256([(a, "D"), (b, None)]) != one


def test_run_key_is_idempotent_per_snapshot_and_algorithm():
    attempt = uuid4()
    snap = scoring.snapshot_sha256([(uuid4(), "A")])
    assert scoring.run_key(attempt, snap) == scoring.run_key(attempt, snap)
    assert scoring.run_key(attempt, snap) != scoring.run_key(attempt, snap, "sc-2")
    assert scoring.run_key(attempt, snap) != scoring.run_key(uuid4(), snap)
    assert len(scoring.run_key(attempt, snap)) == 64


@pytest.mark.parametrize(
    "status,graded,expected",
    [
        ("in_progress", False, "not_submitted"),
        ("submitted", False, "pending"),
        ("graded", False, "pending"),
        ("graded", True, "graded"),
        ("void", True, "void"),
    ],
)
def test_grading_status_pending_is_not_zero(status, graded, expected):
    assert scoring.grading_status(status, graded) == expected


def test_automatic_grade_action():
    result = uuid4()
    assert scoring.automatic_grade_action(None, result) == "insert"
    assert scoring.automatic_grade_action((result, "automatic"), result) == "noop"
    assert scoring.automatic_grade_action((uuid4(), "teacher"), result) == "keep_teacher"
    assert scoring.automatic_grade_action((uuid4(), "automatic"), result) == "insert"


# ---- Grading job with an in-memory sync session ---------------------------------------------


class Result(list):
    def all(self):
        return list(self)

    def first(self):
        return self[0] if self else None


class GradingSession:
    """Answers exactly the statements ``grade_attempt_job`` issues and records the writes."""

    def __init__(self, *, status="submitted", score_release="manual", released_at=None):
        self.workspace = uuid4()
        self.version = uuid4()
        self.items = ids(3)
        self.answers = {self.items[0]: "A", self.items[1]: "C"}  # third left blank
        snapshot = scoring.snapshot_sha256(self.answers.items())
        self.attempt = SimpleNamespace(
            id=uuid4(),
            workspace_id=self.workspace,
            assignment_id=uuid4(),
            exam_version_id=self.version,
            status=status,
            submitted_snapshot_sha256=snapshot,
        )
        self.assignment = SimpleNamespace(
            score_release=score_release, scores_released_at=released_at
        )
        self.results: list[dict] = []
        self.result_items: list[dict] = []
        self.grades: list[dict] = []
        self.statements = []

    def _sql(self, stmt):
        return str(stmt)

    def scalar(self, stmt):
        self.statements.append(stmt)
        sql = self._sql(stmt)
        if "FROM edu.quiz_attempts" in sql and "max(" not in sql:
            return self.attempt
        if "FROM edu.assignments" in sql:
            return self.assignment
        if "max(edu.grades.revision_no)" in sql:
            return max((g["revision_no"] for g in self.grades), default=None)
        if "SELECT edu.grading_results.id" in sql:
            wanted = set(stmt.compile().params.values())
            found = [r["id"] for r in self.results if r["run_key"] in wanted]
            return found[0] if found else None
        raise AssertionError(sql)

    def execute(self, stmt, params=None):
        self.statements.append(stmt)
        if isinstance(stmt, Insert):
            table = stmt.table.name
            if table == "grading_result_items":
                self.result_items.extend(params)
            elif table == "grading_results":
                self.results.append(dict(stmt.compile().params))
            elif table == "grades":
                assert not any(g["is_current"] for g in self.grades), "flip before insert"
                self.grades.append(dict(stmt.compile().params))
            return Result()
        if isinstance(stmt, Update):
            values = stmt.compile().params
            if stmt.table.name == "grades":
                for grade in self.grades:
                    grade["is_current"] = False
            elif stmt.table.name == "quiz_attempts":
                self.attempt.status = values["status"]
            return Result()
        sql = self._sql(stmt)
        if isinstance(stmt, TextClause):
            assert "edu.exam_keys_for_scoring" in sql and params == {"version": self.version}
            keys = ["A", "B", "D"]
            return Result(
                [(item, key + " ", Decimal(1)) for item, key in zip(self.items, keys, strict=True)]
            )
        if "FROM edu.exam_items" in sql:
            choices = [{"key": k, "text": k} for k in "ABCD"]
            return Result([(item, Decimal("1.00"), choices) for item in self.items])
        if "FROM edu.student_answers" in sql:
            return Result([(i, {"selectedKey": k}) for i, k in self.answers.items()])
        if "FROM edu.grades" in sql:
            return Result(
                [
                    (g["id"], g["grading_result_id"], g["approval_mode"])
                    for g in self.grades
                    if g["is_current"]
                ]
            )
        raise AssertionError(sql)

    def flush(self):
        pass


def job_for(session, attempt_id=None):
    return SimpleNamespace(
        input={"attemptId": str(attempt_id or session.attempt.id)},
        workspace_id=session.workspace,
    )


def test_grading_job_scores_records_evidence_and_is_idempotent():
    session = GradingSession()
    first = scoring.grade_attempt_job(session, job_for(session), NOW)
    assert first["action"] == "insert" and first["score"] == "1.00"
    assert first["maxScore"] == "3.00"
    assert len(session.results) == 1 and len(session.result_items) == 3
    assert session.results[0]["algorithm_version"] == "sc-1"
    assert session.results[0]["source"] == "online"
    reasons = sorted(i["reason"] for i in session.result_items)
    assert reasons == ["blank", "correct", "incorrect"]
    blank = next(i for i in session.result_items if i["reason"] == "blank")
    assert blank["answer_source"] == "blank" and blank["awarded_points"] == Decimal("0.00")
    assert session.grades[0]["revision_no"] == 1 and session.grades[0]["is_current"]
    assert session.grades[0]["approval_mode"] == "automatic"
    assert session.grades[0]["released_at"] is None  # manual policy
    assert session.attempt.status == "graded"

    replay = scoring.grade_attempt_job(session, job_for(session), NOW)
    assert replay["action"] == "noop"
    assert replay["gradingResultId"] == first["gradingResultId"]
    assert len(session.results) == 1 and len(session.grades) == 1


def test_immediate_policy_and_released_assignment_release_on_grading():
    immediate = GradingSession(score_release="immediate")
    scoring.grade_attempt_job(immediate, job_for(immediate), NOW)
    assert immediate.grades[0]["released_at"] == NOW
    after_close = GradingSession(score_release="after_close", released_at=NOW)
    scoring.grade_attempt_job(after_close, job_for(after_close), NOW)
    assert after_close.grades[0]["released_at"] == NOW


def test_teacher_override_is_not_superseded_by_regrading():
    session = GradingSession()
    override_result = uuid4()
    session.grades.append(
        {
            "id": uuid4(),
            "grading_result_id": override_result,
            "approval_mode": "teacher",
            "is_current": True,
            "revision_no": 2,
        }
    )
    outcome = scoring.grade_attempt_job(session, job_for(session), NOW)
    assert outcome["action"] == "keep_teacher"
    assert len(session.grades) == 1 and session.grades[0]["is_current"]


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda s: setattr(s.attempt, "status", "in_progress"), "attempt_not_submitted"),
        (lambda s: setattr(s.attempt, "submitted_snapshot_sha256", b"x" * 32), "snapshot_mismatch"),
        (lambda s: setattr(s, "attempt", None), "attempt_not_found"),
    ],
)
def test_grading_rejections_are_permanent(mutate, code):
    session = GradingSession()
    job = job_for(session)
    mutate(session)
    with pytest.raises(scoring.GradingRejected) as caught:
        scoring.grade_attempt_job(session, job, NOW)
    assert caught.value.code == code
    assert session.results == [] and session.grades == []


def test_invalid_job_input_and_void_attempt():
    session = GradingSession()
    with pytest.raises(scoring.GradingRejected):
        scoring.grade_attempt_job(
            session, SimpleNamespace(input={"attemptId": "x"}, workspace_id=None), NOW
        )
    session.attempt.status = "void"
    assert scoring.grade_attempt_job(session, job_for(session), NOW)["action"] == "skipped_void"


def test_handler_registration_maps_rejections_to_permanent_errors():
    assert "attempt.grade" in tasks.HANDLERS
    assert job_service.QUEUE_BY_KIND["attempt.grade"] == "default"
    session = GradingSession(status="in_progress")
    ctx = tasks.HandlerContext(session, job_for(session), store=None, now=NOW)
    with pytest.raises(tasks.PermanentJobError) as caught:
        tasks.grade_attempt(ctx)
    assert caught.value.code == "attempt_not_submitted"


# ---- Sweeper wiring -------------------------------------------------------------------------


class SweepSession:
    def __init__(self, expired, released):
        self.expired, self.released, self.calls = expired, released, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def begin(self):
        return self

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append(sql)
        assert params == {"now": NOW}
        if "edu.expire_attempts" in sql:
            return Result(self.expired)
        if "edu.apply_due_releases" in sql:
            return Result(self.released)
        raise AssertionError(sql)


def test_sweep_expires_enqueues_and_releases():
    jobs = [uuid4(), None]
    expired = [(uuid4(), uuid4(), jobs[0]), (uuid4(), uuid4(), jobs[1])]
    released = [(uuid4(), "scores"), (uuid4(), "solutions"), (uuid4(), "scores")]
    session = SweepSession(expired, released)
    sent = []
    summary = tasks.sweep_assessments(
        sessions=lambda: session, send=lambda *a: sent.append(a), clock=lambda: NOW
    )
    assert summary == {"expired": 2, "scores": 2, "solutions": 1}
    assert sent == [(jobs[0], "attempt.grade")]  # a no-op finalization enqueues nothing
    assert "expire_attempts" in session.calls[0] and "apply_due_releases" in session.calls[1]


def test_sweep_tolerates_broker_failure():
    session = SweepSession([(uuid4(), uuid4(), uuid4())], [])

    def broken(*args):
        raise ConnectionError("broker down")

    summary = tasks.sweep_assessments(sessions=lambda: session, send=broken, clock=lambda: NOW)
    assert summary["expired"] == 1
