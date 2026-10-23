"""Teacher grade override (ASMT-08): append-only evidence and revisions.

An override never edits earlier rows. It appends a ``manual`` grading result that supersedes
the current one, then a ``teacher`` grade revision carrying the reason, after flipping the old
revision's ``is_current`` — all in the caller's transaction with the attempt row locked, so it
serializes with automatic grading. Aggregates read current grades only, so an override replaces
the student's score instead of being counted twice. The new revision is NOT released
automatically; the teacher re-releases explicitly (audited) via ``release-scores``.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.models.assessment import Assignment, Grade, GradingResult, QuizAttempt, exam_versions_ref
from app.services.assessment_common import ATTEMPT_NOT_FOUND, Conflict, Invalid, NotFound, Scope
from app.services.scoring import next_revision, q2

MANUAL_ALGORITHM = "manual-1"
MAX_REASON = 2000


def validate_override(score: Any, reason: Any, max_score: Decimal) -> tuple[Decimal, str]:
    if not isinstance(reason, str) or not reason.strip():
        raise Invalid("reason_required", "Cần nhập lý do điều chỉnh điểm.")
    reason = reason.strip()
    if len(reason) > MAX_REASON:
        raise Invalid("reason_too_long", "Lý do quá dài (tối đa 2000 ký tự).")
    try:
        value = Decimal(str(score))
    except (InvalidOperation, ValueError):
        raise Invalid("invalid_score", "Điểm không hợp lệ.") from None
    if not value.is_finite() or value != value.quantize(Decimal("0.01")):
        raise Invalid("invalid_score", "Điểm chỉ có tối đa 2 chữ số thập phân.")
    if value < 0 or value > max_score:
        raise Invalid("invalid_score", f"Điểm phải nằm trong khoảng 0 đến {max_score}.")
    return q2(value), reason


@dataclass(frozen=True)
class OverrideOutcome:
    attempt_id: UUID
    grading_result_id: UUID
    revision_no: int
    score: Decimal
    max_score: Decimal
    reason: str
    approved_at: datetime


async def override_grade(
    db: AsyncSession,
    scope: Scope,
    assignment: Assignment,
    attempt_id: UUID,
    *,
    score: Any,
    reason: Any,
    now: datetime,
    request_id: str | None = None,
) -> OverrideOutcome:
    attempt = await db.scalar(
        select(QuizAttempt)
        .where(
            QuizAttempt.workspace_id == scope.workspace.id,
            QuizAttempt.assignment_id == assignment.id,
            QuizAttempt.id == attempt_id,
        )
        .with_for_update()
    )
    if attempt is None:
        raise NotFound(*ATTEMPT_NOT_FOUND)
    if attempt.status not in ("submitted", "graded"):
        raise Conflict("attempt_not_submitted", "Chỉ điều chỉnh điểm cho bài đã nộp.")
    current = await db.scalar(
        select(Grade).where(Grade.attempt_id == attempt.id, Grade.is_current.is_(True))
    )
    if current is not None:
        max_score = q2(current.max_score)
    else:
        total = await db.scalar(
            select(exam_versions_ref.c.total_points).where(
                exam_versions_ref.c.workspace_id == scope.workspace.id,
                exam_versions_ref.c.id == attempt.exam_version_id,
            )
        )
        if total is None or q2(total) <= 0:
            raise Conflict("exam_total_missing", "Không xác định được điểm tối đa của đề.")
        max_score = q2(total)
    value, clean_reason = validate_override(score, reason, max_score)

    result_id = uuid4()
    snapshot = attempt.submitted_snapshot_sha256
    await db.execute(
        insert(GradingResult).values(
            id=result_id,
            workspace_id=attempt.workspace_id,
            attempt_id=attempt.id,
            exam_version_id=attempt.exam_version_id,
            run_key="manual:" + uuid4().hex,
            input_hash=bytes(snapshot).hex() if snapshot else "none",
            algorithm_version=MANUAL_ALGORITHM,
            source="manual",
            raw_score=value,
            max_score=max_score,
            status="approved",
            supersedes_id=current.grading_result_id if current is not None else None,
            created_by_user_id=scope.user.id,
            created_at=now,
        )
    )
    max_revision = await db.scalar(
        select(func.max(Grade.revision_no)).where(Grade.attempt_id == attempt.id)
    )
    if current is not None:
        await db.execute(
            update(Grade)
            .where(Grade.id == current.id)
            .values(is_current=False)
            .execution_options(synchronize_session=False)
        )
    revision_no = next_revision(max_revision)
    await db.execute(
        insert(Grade).values(
            id=uuid4(),
            workspace_id=attempt.workspace_id,
            attempt_id=attempt.id,
            grading_result_id=result_id,
            revision_no=revision_no,
            score=value,
            max_score=max_score,
            is_current=True,
            approval_mode="teacher",
            approved_by_user_id=scope.user.id,
            approved_at=now,
            released_at=None,
            reason=clean_reason,
        )
    )
    if attempt.status == "submitted":
        await db.execute(
            update(QuizAttempt)
            .where(QuizAttempt.id == attempt.id)
            .values(status="graded", updated_at=now)
            .execution_options(synchronize_session=False)
        )
    # Audit carries ids and numbers only: no student name, answers or free-text reason.
    audit(
        "grade.override",
        request_id=request_id,
        user_id=scope.user.id,
        workspace_id=scope.workspace.id,
        assignment_id=assignment.id,
        attempt_id=attempt.id,
        revision_no=revision_no,
        previous_score=str(current.score) if current is not None else None,
        score=str(value),
        max_score=str(max_score),
    )
    return OverrideOutcome(attempt.id, result_id, revision_no, value, max_score, clean_reason, now)
