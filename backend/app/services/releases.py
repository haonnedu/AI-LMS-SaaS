"""Separate score and solution release (ASMT-07).

Policies (fixed at publication):

* scores ``immediate``: each automatic grade is released when it is recorded;
  ``after_close``: the sweeper stamps ``assignments.scores_released_at`` once ``closes_at`` has
  passed and releases every current grade; ``manual``: the teacher endpoint does the same.
  After that stamp, later automatic grades (late deadline sweeps) are released on recording.
  Teacher overrides are never auto-released: re-release is an explicit, audited action.
* solutions ``never`` | ``after_close`` | ``manual``: solutions are released only once the
  assignment accepts no new attempts AND no attempt is still in progress, so an answer key can
  never reach a student who can still answer. Release stamps are one-way (database guard).

Students only ever see scores through ``grades.released_at`` and keys through
``edu.student_results`` after ``solutions_released_at``.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.assessment import Assignment, Grade, QuizAttempt
from app.services.assessment_common import Conflict


def automatic_release_at(
    score_release: str, scores_released_at: datetime | None, now: datetime
) -> datetime | None:
    """Release stamp for a grade recorded by automatic grading at ``now``."""
    if score_release == "immediate" or scores_released_at is not None:
        return now
    return None


def score_release_problem(status: str) -> str | None:
    if status not in ("published", "closed"):
        return "assignment_not_published"
    return None


def solution_release_problem(
    *,
    solution_release: str,
    status: str,
    closes_at: datetime | None,
    now: datetime,
    in_progress: int,
) -> str | None:
    """Why solutions cannot be released now (``None`` when they can)."""
    if solution_release == "never":
        return "solutions_disabled"
    if status not in ("published", "closed"):
        return "assignment_not_published"
    accepting = status == "published" and (closes_at is None or closes_at > now)
    if accepting:
        return "assignment_still_open"
    if in_progress > 0:
        return "attempts_in_progress"
    return None


RELEASE_MESSAGES = {
    "assignment_not_published": "Bài được giao chưa được phát hành.",
    "solutions_disabled": "Bài được giao này không công bố đáp án.",
    "assignment_still_open": "Hãy đóng bài được giao trước khi công bố đáp án.",
    "attempts_in_progress": "Vẫn còn học sinh đang làm bài; chưa thể công bố đáp án.",
}


def _conflict(code: str) -> Conflict:
    return Conflict(code, RELEASE_MESSAGES[code])


async def release_scores(db: AsyncSession, assignment: Assignment, now: datetime) -> int:
    """Teacher release (any policy, audited by the caller). ``assignment`` is row-locked.

    Idempotent: stamps the assignment once and releases every current, unreleased grade —
    including a newer override revision, which is how a corrected score is re-released.
    """
    problem = score_release_problem(assignment.status)
    if problem:
        raise _conflict(problem)
    if assignment.scores_released_at is None:
        assignment.scores_released_at = now
        assignment.updated_at = now
        await db.flush()
    result = await db.execute(
        update(Grade)
        .where(
            Grade.workspace_id == assignment.workspace_id,
            Grade.is_current.is_(True),
            Grade.released_at.is_(None),
            Grade.attempt_id.in_(
                select(QuizAttempt.id).where(QuizAttempt.assignment_id == assignment.id)
            ),
        )
        .values(released_at=now)
        .execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def release_solutions(db: AsyncSession, assignment: Assignment, now: datetime) -> bool:
    """Manual solution release; returns False when already released (idempotent)."""
    if assignment.solutions_released_at is not None:
        return False
    in_progress = await db.scalar(
        select(func.count())
        .select_from(QuizAttempt)
        .where(QuizAttempt.assignment_id == assignment.id, QuizAttempt.status == "in_progress")
    )
    problem = solution_release_problem(
        solution_release=assignment.solution_release,
        status=assignment.status,
        closes_at=assignment.closes_at,
        now=now,
        in_progress=int(in_progress or 0),
    )
    if problem:
        raise _conflict(problem)
    assignment.solutions_released_at = now
    assignment.updated_at = now
    await db.flush()
    return True


def apply_due_releases(db: Session, now: datetime) -> list[tuple[UUID, str]]:
    """Sweeper step for ``after_close`` policies (cross-tenant definer function)."""
    rows = db.execute(
        text("SELECT out_assignment_id, out_kind FROM edu.apply_due_releases(:now)"),
        {"now": now},
    ).all()
    return [(row[0], row[1]) for row in rows]


def release_summary(rows: list[tuple[Any, str]]) -> dict[str, int]:
    return {
        "scores": sum(1 for _, kind in rows if kind == "scores"),
        "solutions": sum(1 for _, kind in rows if kind == "solutions"),
    }
