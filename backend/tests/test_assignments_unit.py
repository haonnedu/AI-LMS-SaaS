"""Assignments without PostgreSQL: validation, lifecycle rules, release policies, results."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.sql.dml import Insert, Update

from app.services import assignments as service
from app.services import releases
from app.services.assessment_common import Conflict, Invalid, NotFound

NOW = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


# ---- Timezone and window validation ---------------------------------------------------------


@pytest.mark.parametrize("name", ["Asia/Ho_Chi_Minh", "UTC", "Asia/Bangkok", "Europe/Paris"])
def test_valid_timezones(name):
    assert service.validate_timezone(name) == name


@pytest.mark.parametrize(
    "name", ["", " UTC", "Mars/Olympus", "../../etc/passwd", "Asia/Ho Chi Minh", "x" * 65]
)
def test_invalid_timezones(name):
    with pytest.raises(Invalid) as caught:
        service.validate_timezone(name)
    assert caught.value.code == "invalid_timezone"


def schedule(**overrides):
    values = {
        "opens_at": NOW,
        "closes_at": NOW + HOUR,
        "time_limit_seconds": 600,
        "max_attempts": 1,
        "score_release": "manual",
        "solution_release": "manual",
    } | overrides
    service.validate_schedule(**values)


def test_valid_schedules():
    schedule()
    schedule(closes_at=None, time_limit_seconds=None)
    schedule(score_release="after_close", solution_release="after_close", max_attempts=5)
    schedule(opens_at=datetime(2026, 10, 23, 15, 0, tzinfo=UTC), closes_at=None)


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"opens_at": datetime(2026, 10, 23, 8, 0)}, "invalid_window"),
        ({"closes_at": datetime(2026, 10, 23, 9, 0)}, "invalid_window"),
        ({"closes_at": NOW}, "invalid_window"),
        ({"closes_at": NOW - HOUR}, "invalid_window"),
        ({"time_limit_seconds": 59}, "invalid_time_limit"),
        ({"time_limit_seconds": 86401}, "invalid_time_limit"),
        ({"max_attempts": 0}, "invalid_max_attempts"),
        ({"max_attempts": 6}, "invalid_max_attempts"),
        ({"score_release": "never"}, "invalid_release_policy"),
        ({"solution_release": "immediate"}, "invalid_release_policy"),
        ({"closes_at": None, "score_release": "after_close"}, "invalid_release_policy"),
        ({"closes_at": None, "solution_release": "after_close"}, "invalid_release_policy"),
    ],
)
def test_invalid_schedules(overrides, code):
    with pytest.raises(Invalid) as caught:
        schedule(**overrides)
    assert caught.value.code == code


# ---- Publish / extend rules -----------------------------------------------------------------


def publish_case(**overrides):
    values = {
        "status": "draft",
        "version_status": "published",
        "item_types": ["single_choice"] * 3,
        "closes_at": NOW + HOUR,
        "class_status": "active",
        "now": NOW,
    } | overrides
    return service.publish_problem(**values)


@pytest.mark.parametrize(
    "overrides,problem",
    [
        ({}, None),
        ({"closes_at": None}, None),
        ({"status": "closed"}, "invalid_transition"),
        ({"version_status": "draft"}, "exam_version_not_published"),
        ({"version_status": "archived"}, "exam_version_not_published"),
        ({"version_status": None}, "exam_version_not_published"),
        ({"item_types": []}, "exam_version_empty"),
        ({"item_types": ["single_choice", "essay"]}, "unsupported_item_type"),
        ({"class_status": "archived"}, "class_archived"),
        ({"closes_at": NOW}, "closes_in_past"),
    ],
)
def test_publish_rules(overrides, problem):
    assert publish_case(**overrides) == problem


@pytest.mark.parametrize(
    "status,old,new,problem",
    [
        ("draft", None, NOW + HOUR, None),
        ("draft", NOW + 2 * HOUR, NOW + HOUR, None),  # drafts are freely editable
        ("published", NOW + HOUR, NOW + 2 * HOUR, None),
        ("closed", NOW + HOUR, NOW + 2 * HOUR, None),
        ("published", NOW + HOUR, NOW + HOUR, "extend_only_later"),
        ("published", NOW + HOUR, NOW + HOUR / 2, "extend_only_later"),
        ("published", NOW - 2 * HOUR, NOW - HOUR, "extend_only_later"),
        ("published", None, NOW + HOUR, "no_closing_time"),
        ("archived", NOW + HOUR, NOW + 2 * HOUR, "invalid_transition"),
        ("draft", None, NOW - 4 * HOUR, "invalid_window"),
    ],
)
def test_extend_rules(status, old, new, problem):
    opens = NOW - 3 * HOUR
    assert service.extend_problem(status=status, opens_at=opens, old=old, new=new, now=NOW) == (
        problem
    )


# ---- Release policies -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "policy,stamp,expected",
    [
        ("immediate", None, NOW),
        ("after_close", None, None),
        ("manual", None, None),
        ("after_close", NOW - HOUR, NOW),
        ("manual", NOW - HOUR, NOW),
    ],
)
def test_automatic_release(policy, stamp, expected):
    assert releases.automatic_release_at(policy, stamp, NOW) == expected


@pytest.mark.parametrize(
    "policy,status,closes,in_progress,problem",
    [
        ("never", "closed", NOW - HOUR, 0, "solutions_disabled"),
        ("manual", "draft", None, 0, "assignment_not_published"),
        ("manual", "published", None, 0, "assignment_still_open"),
        ("manual", "published", NOW + HOUR, 0, "assignment_still_open"),
        ("manual", "published", NOW - HOUR, 0, None),
        ("manual", "closed", NOW + HOUR, 1, "attempts_in_progress"),
        ("manual", "closed", None, 0, None),
        ("after_close", "published", NOW - HOUR, 2, "attempts_in_progress"),
    ],
)
def test_solution_release_requires_no_open_opportunity(
    policy, status, closes, in_progress, problem
):
    assert (
        releases.solution_release_problem(
            solution_release=policy,
            status=status,
            closes_at=closes,
            now=NOW,
            in_progress=in_progress,
        )
        == problem
    )


# ---- Results and denominators ---------------------------------------------------------------


def attempt(student, no, status, submitted=True):
    return service.AttemptFacts(uuid4(), student, no, status, NOW if submitted else None)


def test_denominators_pending_is_not_zero_and_counts_each_student_once():
    a, b, c, d, e = (uuid4() for _ in range(5))
    roster = [(a, "An"), (b, "Bình"), (c, "Chi"), (d, "Dũng"), (e, "Em")]
    b1 = attempt(b, 1, "in_progress", submitted=False)
    c1 = attempt(c, 1, "submitted")
    d1 = attempt(d, 1, "graded")
    e1 = attempt(e, 1, "graded")
    e2 = attempt(e, 2, "submitted")  # latest submitted retake is awaiting grading
    void = attempt(a, 1, "void")
    grades = {d1.attempt_id: (Decimal("7.50"), Decimal("10.00"))}
    grades[e1.attempt_id] = (Decimal("9.00"), Decimal("10.00"))
    denominators, rows = service.build_results(roster, [b1, c1, d1, e1, e2, void], grades)
    assert denominators == service.Denominators(
        enrolled=5, started=4, submitted=3, graded=1, pending=2
    )
    by_name = {row.display_name: row for row in rows}
    assert by_name["An"].status == "not_started" and by_name["An"].score is None
    assert by_name["Bình"].grading_status == "not_submitted"
    assert by_name["Chi"].grading_status == "pending" and by_name["Chi"].score is None
    assert by_name["Dũng"].score == Decimal("7.50") and by_name["Dũng"].grading_status == "graded"
    # No fallback to the older graded attempt: the latest submission shows as pending.
    assert by_name["Em"].attempt_no == 2 and by_name["Em"].score is None
    assert by_name["Em"].grading_status == "pending"


def test_override_replaces_score_instead_of_double_counting():
    student = uuid4()
    graded = attempt(student, 1, "graded")
    # Only the current revision is passed in (Grade.is_current), whatever the history length.
    denominators, rows = service.build_results(
        [(student, "An")], [graded], {graded.attempt_id: (Decimal("8.00"), Decimal("10.00"))}
    )
    assert denominators.graded == 1 and denominators.submitted == 1
    assert rows[0].score == Decimal("8.00")


def test_results_csv_scores_only_and_neutralizes_formulas():
    row = service.ResultRow(
        student_id=uuid4(),
        display_name="=HYPERLINK(1)",
        attempt_id=uuid4(),
        attempt_no=1,
        status="graded",
        score=Decimal("1.50"),
        max_score=Decimal("2.00"),
        grading_status="graded",
        submitted_at=NOW,
    )
    body = service.results_csv([row])
    assert body.startswith("\ufeff")
    lines = body.lstrip("\ufeff").splitlines()
    assert lines[0].split(",") == list(service.CSV_HEADER)
    assert "'=HYPERLINK(1)" in lines[1] and ",1.50,2.00," in lines[1]
    lowered = body.lower()
    assert "correct" not in lowered and "explanation" not in lowered and "đáp án" not in lowered


# ---- Lifecycle with a queued fake session ---------------------------------------------------


class Result(list):
    rowcount = 0

    def all(self):
        return list(self)

    def first(self):
        return self[0] if self else None


class QueueSession:
    """Serves queued answers in call order; records writes."""

    def __init__(self, scalar=(), execute=(), scalars=()):
        self.scalar_queue, self.execute_queue = list(scalar), list(execute)
        self.scalars_queue = list(scalars)
        self.writes = []
        self.flushes = 0

    async def scalar(self, stmt, params=None):
        if isinstance(stmt, Insert):
            self.writes.append(stmt)
        return self.scalar_queue.pop(0)

    async def scalars(self, stmt, params=None):
        return Result(self.scalars_queue.pop(0))

    async def execute(self, stmt, params=None):
        if isinstance(stmt, Insert | Update):
            self.writes.append(stmt)
            result = Result()
            result.rowcount = 3
            return result
        return Result(self.execute_queue.pop(0))

    async def flush(self):
        self.flushes += 1


def scope(role="teacher"):
    return SimpleNamespace(
        user=SimpleNamespace(id=uuid4()), workspace=SimpleNamespace(id=uuid4()), role=role
    )


def assignment_row(**overrides):
    values = {
        "id": uuid4(),
        "workspace_id": uuid4(),
        "class_id": uuid4(),
        "exam_version_id": uuid4(),
        "status": "draft",
        "opens_at": NOW - HOUR,
        "closes_at": NOW + HOUR,
        "time_limit_seconds": 600,
        "solution_release": "manual",
        "scores_released_at": None,
        "solutions_released_at": None,
        "published_at": None,
        "updated_at": None,
    } | overrides
    return SimpleNamespace(**values)


ACTIVE_CLASS = SimpleNamespace(id=uuid4(), status="active")


async def test_publish_requires_published_exam_version():
    assignment = assignment_row()
    db = QueueSession(
        scalar=[assignment, ACTIVE_CLASS, ACTIVE_CLASS],
        execute=[[(assignment.exam_version_id, "draft", Decimal(1))]],
        scalars=[["single_choice"]],
    )
    with pytest.raises(Conflict) as caught:
        await service.publish(db, scope(), assignment.id, NOW)
    assert caught.value.code == "exam_version_not_published"
    assert assignment.status == "draft" and db.flushes == 0


async def test_publish_pins_and_stamps():
    assignment = assignment_row()
    db = QueueSession(
        scalar=[assignment, ACTIVE_CLASS, ACTIVE_CLASS],
        execute=[[(assignment.exam_version_id, "published", Decimal(2))]],
        scalars=[["single_choice", "single_choice"]],
    )
    published = await service.publish(db, scope(), assignment.id, NOW)
    assert published.status == "published" and published.published_at == NOW
    # Idempotent repeat touches nothing.
    again = QueueSession(scalar=[published, ACTIVE_CLASS])
    assert (await service.publish(again, scope(), assignment.id, NOW)) is published


async def test_invisible_assignment_or_class_is_404():
    with pytest.raises(NotFound) as caught:
        await service.get_assignment(QueueSession(scalar=[None]), scope(), uuid4())
    assert caught.value.code == "assignment_not_found"
    with pytest.raises(NotFound) as caught:  # assignment exists but the teacher lacks the class
        await service.get_assignment(
            QueueSession(scalar=[assignment_row(), None]), scope(), uuid4()
        )
    assert caught.value.code == "assignment_not_found"


async def test_create_validates_class_timezone_and_version():
    kwargs = {
        "exam_version_id": uuid4(),
        "title": "Kiểm tra 15 phút",
        "instructions": None,
        "opens_at": NOW,
        "closes_at": NOW + HOUR,
        "time_limit_seconds": 900,
        "max_attempts": 1,
        "timezone": "Asia/Ho_Chi_Minh",
        "score_release": "immediate",
        "solution_release": "manual",
    }
    archived = SimpleNamespace(id=uuid4(), status="archived")
    with pytest.raises(Conflict):
        await service.create_assignment(QueueSession(scalar=[archived]), scope(), uuid4(), **kwargs)
    with pytest.raises(Invalid):
        await service.create_assignment(
            QueueSession(scalar=[ACTIVE_CLASS]), scope(), uuid4(), **kwargs | {"timezone": "X/Y"}
        )
    with pytest.raises(NotFound) as caught:
        await service.create_assignment(
            QueueSession(scalar=[ACTIVE_CLASS], execute=[[]]), scope(), uuid4(), **kwargs
        )
    assert caught.value.code == "exam_version_not_found"
    created = SimpleNamespace(id=uuid4())
    db = QueueSession(
        scalar=[ACTIVE_CLASS, created], execute=[[(kwargs["exam_version_id"], "draft", None)]]
    )
    assert await service.create_assignment(db, scope(), uuid4(), **kwargs) is created
    params = db.writes[0].compile().params
    assert "status" not in params  # the database default (draft) applies
    assert params["exam_version_id"] == kwargs["exam_version_id"]
    assert params["timezone"] == "Asia/Ho_Chi_Minh"


async def test_close_and_extend_transitions():
    with pytest.raises(Conflict):
        await service.close(
            QueueSession(scalar=[assignment_row(), ACTIVE_CLASS]), scope(), uuid4(), NOW
        )
    published = assignment_row(status="published", published_at=NOW - HOUR)
    with pytest.raises(Invalid):
        await service.extend(
            QueueSession(scalar=[published, ACTIVE_CLASS]), scope(), uuid4(), NOW + HOUR / 2, NOW
        )
    db = QueueSession(scalar=[published, ACTIVE_CLASS])
    extended = await service.extend(db, scope(), uuid4(), NOW + 3 * HOUR, NOW)
    assert extended.closes_at == NOW + 3 * HOUR
    update = db.writes[-1]
    assert update.table.name == "quiz_attempts"  # open attempts get the later deadline
    with pytest.raises(Invalid):
        await service.extend(
            QueueSession(), scope(), uuid4(), datetime(2026, 10, 24, 8, 0), NOW
        )  # naive datetime rejected before any query


async def test_release_scores_and_solutions():
    draft = assignment_row()
    with pytest.raises(Conflict):
        await releases.release_scores(QueueSession(), draft, NOW)
    published = assignment_row(status="published", published_at=NOW - HOUR)
    db = QueueSession()
    assert await releases.release_scores(db, published, NOW) == 3
    assert published.scores_released_at == NOW
    assert db.writes[-1].table.name == "grades"
    later = NOW + HOUR
    await releases.release_scores(QueueSession(), published, later)
    assert published.scores_released_at == NOW  # the first stamp is kept

    with pytest.raises(Conflict) as caught:
        await releases.release_solutions(QueueSession(scalar=[0]), published, NOW)
    assert caught.value.code == "assignment_still_open"
    closed = assignment_row(status="closed", published_at=NOW - HOUR)
    with pytest.raises(Conflict) as caught:
        await releases.release_solutions(QueueSession(scalar=[1]), closed, NOW)
    assert caught.value.code == "attempts_in_progress"
    assert await releases.release_solutions(QueueSession(scalar=[0]), closed, NOW) is True
    assert closed.solutions_released_at == NOW
    assert await releases.release_solutions(QueueSession(), closed, later) is False
