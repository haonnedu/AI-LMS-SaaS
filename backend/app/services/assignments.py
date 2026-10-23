"""Teacher-side assignments (ASSIGN-01) and results (ASMT-09 backend).

Every function expects ``workspace_transaction`` (membership + RLS context) and authorizes
class access through ``app.services.classes.get_class``: owners/admins see every class,
teachers only classes they teach. Invisible assignments answer 404.

Publication pins the class and the exam version; the database guard freezes the pin, window
start, time limit, attempt limit and release policies afterwards (``closes_at`` may only move
later). Editing the exam draft never changes what was assigned: the pin is a published,
immutable exam version.
"""

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import (
    Assignment,
    Grade,
    GradingResult,
    GradingResultItem,
    QuizAttempt,
    StudentAnswer,
    exam_items_ref,
    exam_versions_ref,
)
from app.models.teaching import Enrollment, Student
from app.services import classes as class_service
from app.services.assessment_common import (
    ASSIGNMENT_NOT_FOUND,
    ATTEMPT_NOT_FOUND,
    Conflict,
    Invalid,
    NotFound,
    Scope,
)
from app.services.classes import TeachingError
from app.services.scoring import grading_status, selected_key

SCORE_RELEASES = ("immediate", "after_close", "manual")
SOLUTION_RELEASES = ("never", "after_close", "manual")
MIN_TIME_LIMIT = 60
MAX_TIME_LIMIT = 86400
MAX_ATTEMPTS = 5
DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"


# ---- Pure validation ------------------------------------------------------------------------


def validate_timezone(name: str) -> str:
    """IANA zone name used to display the window; stored values are always UTC instants."""
    if not isinstance(name, str) or not 1 <= len(name) <= 64 or name != name.strip():
        raise Invalid("invalid_timezone", "Múi giờ không hợp lệ.")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise Invalid("invalid_timezone", "Múi giờ không hợp lệ.") from None
    return name


def _aware(value: datetime | None, field: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise Invalid("invalid_window", f"{field} phải có múi giờ (ISO 8601 kèm độ lệch).")


def validate_schedule(
    *,
    opens_at: datetime,
    closes_at: datetime | None,
    time_limit_seconds: int | None,
    max_attempts: int,
    score_release: str,
    solution_release: str,
) -> None:
    _aware(opens_at, "opensAt")
    _aware(closes_at, "closesAt")
    if closes_at is not None and closes_at <= opens_at:
        raise Invalid("invalid_window", "Thời điểm đóng phải sau thời điểm mở.")
    if time_limit_seconds is not None and not (
        MIN_TIME_LIMIT <= time_limit_seconds <= MAX_TIME_LIMIT
    ):
        raise Invalid("invalid_time_limit", "Thời gian làm bài phải từ 1 phút đến 24 giờ.")
    if not 1 <= max_attempts <= MAX_ATTEMPTS:
        raise Invalid("invalid_max_attempts", "Số lượt làm bài phải từ 1 đến 5.")
    if score_release not in SCORE_RELEASES or solution_release not in SOLUTION_RELEASES:
        raise Invalid("invalid_release_policy", "Chính sách công bố không hợp lệ.")
    if closes_at is None and "after_close" in (score_release, solution_release):
        raise Invalid("invalid_release_policy", "Công bố sau khi đóng cần có thời điểm đóng bài.")


def publish_problem(
    *,
    status: str,
    version_status: str | None,
    item_types: Sequence[str],
    closes_at: datetime | None,
    class_status: str,
    now: datetime,
) -> str | None:
    if status != "draft":
        return "invalid_transition"
    if version_status != "published":
        return "exam_version_not_published"
    if not item_types:
        return "exam_version_empty"
    if any(kind != "single_choice" for kind in item_types):
        return "unsupported_item_type"
    if class_status != "active":
        return "class_archived"
    if closes_at is not None and closes_at <= now:
        return "closes_in_past"
    return None


def extend_problem(
    *, status: str, opens_at: datetime, old: datetime | None, new: datetime, now: datetime
) -> str | None:
    if status == "archived":
        return "invalid_transition"
    if new <= opens_at:
        return "invalid_window"
    if status == "draft":
        return None
    if old is None:
        return "no_closing_time"
    if new <= old or new <= now:
        return "extend_only_later"
    return None


PROBLEM_MESSAGES = {
    "invalid_transition": "Không thể thực hiện thao tác ở trạng thái hiện tại.",
    "exam_version_not_published": "Chỉ giao được phiên bản đề đã xuất bản.",
    "exam_version_empty": "Phiên bản đề chưa có câu hỏi.",
    "unsupported_item_type": "Bài trực tuyến chỉ hỗ trợ câu hỏi một lựa chọn.",
    "class_archived": "Lớp học đã được lưu trữ.",
    "closes_in_past": "Thời điểm đóng đã qua.",
    "invalid_window": "Thời điểm đóng phải sau thời điểm mở.",
    "no_closing_time": "Bài không có thời điểm đóng nên không thể gia hạn.",
    "extend_only_later": "Chỉ có thể gia hạn tới một thời điểm muộn hơn.",
}


def _problem(code: str) -> Exception:
    message = PROBLEM_MESSAGES[code]
    if code in ("invalid_window", "extend_only_later"):
        return Invalid(code, message)
    return Conflict(code, message)


# ---- Lookup and authorization ---------------------------------------------------------------


async def _authorized_class(db: AsyncSession, scope: Scope, class_id: UUID):
    try:
        return await class_service.get_class(db, scope, class_id)
    except TeachingError as exc:
        if exc.status == 404:
            raise NotFound(*ASSIGNMENT_NOT_FOUND) from None
        raise


async def get_assignment(
    db: AsyncSession, scope: Scope, assignment_id: UUID, *, for_update: bool = False
) -> Assignment:
    query = select(Assignment).where(
        Assignment.workspace_id == scope.workspace.id, Assignment.id == assignment_id
    )
    if for_update:
        query = query.with_for_update()
    assignment = await db.scalar(query)
    if assignment is None:
        raise NotFound(*ASSIGNMENT_NOT_FOUND)
    await _authorized_class(db, scope, assignment.class_id)
    return assignment


async def _version(db: AsyncSession, scope: Scope, version_id: UUID):
    return (
        await db.execute(
            select(
                exam_versions_ref.c.id,
                exam_versions_ref.c.status,
                exam_versions_ref.c.total_points,
            ).where(
                exam_versions_ref.c.workspace_id == scope.workspace.id,
                exam_versions_ref.c.id == version_id,
            )
        )
    ).first()


# ---- Lifecycle ------------------------------------------------------------------------------


async def create_assignment(
    db: AsyncSession,
    scope: Scope,
    class_id: UUID,
    *,
    exam_version_id: UUID,
    title: str,
    instructions: str | None,
    opens_at: datetime,
    closes_at: datetime | None,
    time_limit_seconds: int | None,
    max_attempts: int,
    timezone: str,
    score_release: str,
    solution_release: str,
) -> Assignment:
    school_class = await _authorized_class(db, scope, class_id)
    if school_class.status != "active":
        raise _problem("class_archived")
    validate_timezone(timezone)
    validate_schedule(
        opens_at=opens_at,
        closes_at=closes_at,
        time_limit_seconds=time_limit_seconds,
        max_attempts=max_attempts,
        score_release=score_release,
        solution_release=solution_release,
    )
    version = await _version(db, scope, exam_version_id)
    if version is None:
        raise NotFound("exam_version_not_found", "Không tìm thấy phiên bản đề.")
    if version[1] == "archived":
        raise Conflict("exam_version_archived", "Phiên bản đề đã được lưu trữ.")
    return await db.scalar(
        insert(Assignment)
        .values(
            workspace_id=scope.workspace.id,
            class_id=school_class.id,
            exam_version_id=exam_version_id,
            title=title,
            instructions=instructions,
            opens_at=opens_at,
            closes_at=closes_at,
            time_limit_seconds=time_limit_seconds,
            max_attempts=max_attempts,
            timezone=timezone,
            score_release=score_release,
            solution_release=solution_release,
            created_by_user_id=scope.user.id,
        )
        .returning(Assignment)
    )


async def list_assignments(db: AsyncSession, scope: Scope, class_id: UUID) -> list[Assignment]:
    school_class = await _authorized_class(db, scope, class_id)
    rows = await db.scalars(
        select(Assignment)
        .where(
            Assignment.workspace_id == scope.workspace.id,
            Assignment.class_id == school_class.id,
        )
        .order_by(Assignment.created_at.desc(), Assignment.id)
        .limit(200)
    )
    return list(rows.all())


async def publish(db: AsyncSession, scope: Scope, assignment_id: UUID, now: datetime):
    assignment = await get_assignment(db, scope, assignment_id, for_update=True)
    if assignment.status == "published":
        return assignment  # idempotent repeat
    school_class = await _authorized_class(db, scope, assignment.class_id)
    version = await _version(db, scope, assignment.exam_version_id)
    item_types = (
        await db.scalars(
            select(exam_items_ref.c.item_type).where(
                exam_items_ref.c.workspace_id == scope.workspace.id,
                exam_items_ref.c.exam_version_id == assignment.exam_version_id,
            )
        )
    ).all()
    problem = publish_problem(
        status=assignment.status,
        version_status=version[1] if version else None,
        item_types=list(item_types),
        closes_at=assignment.closes_at,
        class_status=school_class.status,
        now=now,
    )
    if problem:
        raise _problem(problem)
    assignment.status = "published"
    assignment.published_at = now
    assignment.updated_at = now
    await db.flush()
    return assignment


async def close(db: AsyncSession, scope: Scope, assignment_id: UUID, now: datetime):
    """Stop new attempts. Attempts already in progress keep their own deadline."""
    assignment = await get_assignment(db, scope, assignment_id, for_update=True)
    if assignment.status == "closed":
        return assignment
    if assignment.status != "published":
        raise _problem("invalid_transition")
    assignment.status = "closed"
    assignment.updated_at = now
    await db.flush()
    return assignment


async def extend(
    db: AsyncSession, scope: Scope, assignment_id: UUID, closes_at: datetime, now: datetime
):
    """Move ``closes_at`` later; open attempts get the later effective deadline too."""
    _aware(closes_at, "closesAt")
    assignment = await get_assignment(db, scope, assignment_id, for_update=True)
    problem = extend_problem(
        status=assignment.status,
        opens_at=assignment.opens_at,
        old=assignment.closes_at,
        new=closes_at,
        now=now,
    )
    if problem:
        raise _problem(problem)
    assignment.closes_at = closes_at
    assignment.updated_at = now
    await db.flush()
    if assignment.status != "draft":
        limit = assignment.time_limit_seconds
        deadline = (
            func.least(closes_at, QuizAttempt.started_at + timedelta(seconds=limit))
            if limit
            else closes_at
        )
        await db.execute(
            update(QuizAttempt)
            .where(
                QuizAttempt.assignment_id == assignment.id,
                QuizAttempt.status == "in_progress",
            )
            .values(deadline_at=deadline, updated_at=now)
            .execution_options(synchronize_session=False)
        )
    return assignment


async def archive(db: AsyncSession, scope: Scope, assignment_id: UUID, now: datetime):
    """Terminal. Hides the assignment from students and blocks new answers."""
    assignment = await get_assignment(db, scope, assignment_id, for_update=True)
    if assignment.status == "archived":
        return assignment
    assignment.status = "archived"
    assignment.updated_at = now
    await db.flush()
    return assignment


# ---- Results --------------------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptFacts:
    attempt_id: UUID
    student_id: UUID
    attempt_no: int
    status: str
    submitted_at: datetime | None


@dataclass(frozen=True)
class ResultRow:
    student_id: UUID
    display_name: str
    attempt_id: UUID | None
    attempt_no: int | None
    status: str  # not_started | in_progress | submitted | graded
    score: Decimal | None
    max_score: Decimal | None
    grading_status: str  # not_started | not_submitted | pending | graded
    submitted_at: datetime | None


@dataclass(frozen=True)
class Denominators:
    enrolled: int
    started: int
    submitted: int
    graded: int
    pending: int


def _counted_attempt(attempts: Sequence[AttemptFacts]) -> AttemptFacts | None:
    """Gradebook attempt: latest submitted non-void attempt, else the open one."""
    submitted = [a for a in attempts if a.status in ("submitted", "graded")]
    if submitted:
        return max(submitted, key=lambda a: a.attempt_no)
    open_ = [a for a in attempts if a.status == "in_progress"]
    return max(open_, key=lambda a: a.attempt_no) if open_ else None


def build_results(
    roster: Iterable[tuple[UUID, str]],
    attempts: Iterable[AttemptFacts],
    current_grades: dict[UUID, tuple[Decimal, Decimal]],
) -> tuple[Denominators, list[ResultRow]]:
    """Counts each active student once, from current grades only (overrides never double count).

    A submitted attempt without a current grade is ``pending`` with ``score=None`` (never 0).
    """
    by_student: dict[UUID, list[AttemptFacts]] = {}
    for attempt in attempts:
        if attempt.status != "void":
            by_student.setdefault(attempt.student_id, []).append(attempt)
    rows: list[ResultRow] = []
    started = submitted = graded = 0
    for student_id, name in roster:
        own = by_student.get(student_id, [])
        chosen = _counted_attempt(own)
        started += 1 if own else 0
        if chosen is None:
            rows.append(
                ResultRow(
                    student_id, name, None, None, "not_started", None, None, "not_started", None
                )
            )
            continue
        grade = current_grades.get(chosen.attempt_id)
        status = grading_status(chosen.status, grade is not None)
        if chosen.status in ("submitted", "graded"):
            submitted += 1
            graded += 1 if grade is not None else 0
        rows.append(
            ResultRow(
                student_id=student_id,
                display_name=name,
                attempt_id=chosen.attempt_id,
                attempt_no=chosen.attempt_no,
                status=chosen.status,
                score=grade[0] if grade else None,
                max_score=grade[1] if grade else None,
                grading_status=status,
                submitted_at=chosen.submitted_at,
            )
        )
    enrolled = len(rows)
    return Denominators(enrolled, started, submitted, graded, submitted - graded), rows


async def results(db: AsyncSession, scope: Scope, assignment_id: UUID):
    assignment = await get_assignment(db, scope, assignment_id)
    roster = (
        await db.execute(
            select(Enrollment.student_id, Student.display_name)
            .join(
                Student,
                (Student.id == Enrollment.student_id)
                & (Student.workspace_id == Enrollment.workspace_id),
            )
            .where(Enrollment.class_id == assignment.class_id, Enrollment.status == "active")
            .order_by(Student.display_name, Enrollment.student_id)
        )
    ).all()
    attempts = (
        await db.execute(
            select(
                QuizAttempt.id,
                QuizAttempt.student_id,
                QuizAttempt.attempt_no,
                QuizAttempt.status,
                QuizAttempt.submitted_at,
            ).where(QuizAttempt.assignment_id == assignment.id, QuizAttempt.status != "void")
        )
    ).all()
    grades = (
        await db.execute(
            select(Grade.attempt_id, Grade.score, Grade.max_score)
            .join(QuizAttempt, QuizAttempt.id == Grade.attempt_id)
            .where(QuizAttempt.assignment_id == assignment.id, Grade.is_current.is_(True))
        )
    ).all()
    denominators, rows = build_results(
        [(r[0], r[1]) for r in roster],
        [AttemptFacts(*r) for r in attempts],
        {r[0]: (r[1], r[2]) for r in grades},
    )
    return assignment, denominators, rows


CSV_HEADER = (
    "Mã học sinh",
    "Học sinh",
    "Lượt",
    "Trạng thái",
    "Điểm",
    "Điểm tối đa",
    "Chấm điểm",
    "Nộp lúc",
)


def _cell(value: Any) -> str:
    """Neutralize spreadsheet formulas (CSV injection) in user-controlled cells."""
    out = "" if value is None else str(value)
    return "'" + out if out[:1] in ("=", "+", "-", "@", "\t", "\r") else out


def results_csv(rows: Sequence[ResultRow]) -> str:
    """Scores only: no answers, keys or explanations."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for row in rows:
        writer.writerow(
            [
                _cell(row.student_id),
                _cell(row.display_name),
                _cell(row.attempt_no),
                _cell(row.status),
                _cell(row.score),
                _cell(row.max_score),
                _cell(row.grading_status),
                _cell(row.submitted_at.isoformat() if row.submitted_at else None),
            ]
        )
    return "\ufeff" + buffer.getvalue()  # BOM: Excel opens UTF-8


# ---- Teacher attempt view -------------------------------------------------------------------


@dataclass(frozen=True)
class TeacherItem:
    item_id: UUID
    position: int
    stem: str
    choices: list[dict[str, Any]]
    points: Decimal
    correct_key: str | None
    selected_key: str | None
    answer_revision: int
    awarded_points: Decimal | None
    reason: str | None


@dataclass(frozen=True)
class GradeRevision:
    revision_no: int
    score: Decimal
    max_score: Decimal
    approval_mode: str
    is_current: bool
    reason: str | None
    approved_at: datetime
    released_at: datetime | None


@dataclass(frozen=True)
class TeacherAttemptView:
    attempt: QuizAttempt
    display_name: str
    items: list[TeacherItem]
    grades: list[GradeRevision]
    grading_status: str


async def teacher_attempt(
    db: AsyncSession, scope: Scope, assignment_id: UUID, attempt_id: UUID
) -> TeacherAttemptView:
    assignment = await get_assignment(db, scope, assignment_id)
    attempt = await db.scalar(
        select(QuizAttempt).where(
            QuizAttempt.workspace_id == scope.workspace.id,
            QuizAttempt.assignment_id == assignment.id,
            QuizAttempt.id == attempt_id,
        )
    )
    if attempt is None:
        raise NotFound(*ATTEMPT_NOT_FOUND)
    name = await db.scalar(
        select(Student.display_name).where(
            Student.workspace_id == scope.workspace.id, Student.id == attempt.student_id
        )
    )
    items = (
        await db.execute(
            select(
                exam_items_ref.c.id,
                exam_items_ref.c.position,
                exam_items_ref.c.stem,
                exam_items_ref.c.choices,
                exam_items_ref.c.points,
            )
            .where(
                exam_items_ref.c.workspace_id == scope.workspace.id,
                exam_items_ref.c.exam_version_id == attempt.exam_version_id,
            )
            .order_by(exam_items_ref.c.position)
        )
    ).all()
    keys = {
        row[0]: (str(row[1]).strip() if row[1] is not None else None)
        for row in (
            await db.execute(
                text("SELECT exam_item_id, correct_key FROM edu.exam_keys_for_scoring(:version)"),
                {"version": attempt.exam_version_id},
            )
        ).all()
    }
    answers = {
        row[0]: (selected_key(row[1]), row[2])
        for row in (
            await db.execute(
                select(
                    StudentAnswer.exam_item_id,
                    StudentAnswer.response,
                    StudentAnswer.answer_revision,
                ).where(StudentAnswer.attempt_id == attempt.id)
            )
        ).all()
    }
    revisions = (
        await db.scalars(
            select(Grade).where(Grade.attempt_id == attempt.id).order_by(Grade.revision_no)
        )
    ).all()
    current = next((g for g in revisions if g.is_current), None)
    # Per-item evidence: the latest online grading result (a manual override has no items).
    result_id = await db.scalar(
        select(GradingResult.id)
        .where(GradingResult.attempt_id == attempt.id, GradingResult.source == "online")
        .order_by(GradingResult.created_at.desc())
        .limit(1)
    )
    outcomes: dict[UUID, tuple[Decimal, str | None]] = {}
    if result_id is not None:
        for row in (
            await db.execute(
                select(
                    GradingResultItem.exam_item_id,
                    GradingResultItem.awarded_points,
                    GradingResultItem.reason,
                ).where(GradingResultItem.grading_result_id == result_id)
            )
        ).all():
            outcomes[row[0]] = (row[1], row[2])
    view_items = [
        TeacherItem(
            item_id=row[0],
            position=row[1],
            stem=row[2],
            choices=[
                {"key": c.get("key"), "text": c.get("text")}
                for c in (row[3] or [])
                if isinstance(c, dict)
            ],
            points=row[4],
            correct_key=keys.get(row[0]),
            selected_key=answers.get(row[0], (None, 0))[0],
            answer_revision=answers.get(row[0], (None, 0))[1],
            awarded_points=outcomes.get(row[0], (None, None))[0],
            reason=outcomes.get(row[0], (None, None))[1],
        )
        for row in items
    ]
    history = [
        GradeRevision(
            revision_no=g.revision_no,
            score=g.score,
            max_score=g.max_score,
            approval_mode=g.approval_mode,
            is_current=g.is_current,
            reason=g.reason,
            approved_at=g.approved_at,
            released_at=g.released_at,
        )
        for g in revisions
    ]
    return TeacherAttemptView(
        attempt=attempt,
        display_name=name or "",
        items=view_items,
        grades=history,
        grading_status=grading_status(attempt.status, current is not None),
    )
