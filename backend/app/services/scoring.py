"""Deterministic single-choice scoring (ASMT-06) and the ``attempt.grade`` job.

``score_single_choice`` is pure: fixed two-decimal ``Decimal`` arithmetic, no negative or
partial credit, a missing/blank answer scores 0 and is recorded as ``blank``, an option that is
not part of the item scores 0 with reason ``invalid_option``. ``algorithm_version`` is part of
the idempotent ``run_key`` so a replayed job can never create a second result for the same
answer snapshot, while a future algorithm change produces a new, separately audited result.

The job runs in the worker under the job's verified teacher context (RLS applies). Keys are
read only through ``edu.exam_keys_for_scoring``; the runtime role has no SELECT on keys.
"""

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.orm import Session

from app.models.assessment import (
    Assignment,
    Grade,
    GradingResult,
    GradingResultItem,
    QuizAttempt,
    StudentAnswer,
    exam_items_ref,
)
from app.services.releases import automatic_release_at

ALGORITHM_VERSION = "sc-1"
CENT = Decimal("0.01")

Reason = Literal["correct", "incorrect", "blank", "invalid_option"]
GradingStatus = Literal["not_submitted", "pending", "graded", "void"]


def q2(value: Any) -> Decimal:
    """Fixed precision used everywhere a score is stored or compared (numeric(10,2))."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ScoringItem:
    item_id: UUID
    points: Decimal
    correct_key: str | None
    choice_keys: frozenset[str] | None = None  # None: options are not re-validated


@dataclass(frozen=True)
class ItemOutcome:
    item_id: UUID
    selected_key: str | None
    answer_source: Literal["submitted", "blank"]
    reason: Reason
    awarded_points: Decimal
    max_points: Decimal

    @property
    def effective_response(self) -> dict[str, str | None]:
        return {"selectedKey": self.selected_key}


@dataclass(frozen=True)
class ScoreBreakdown:
    items: tuple[ItemOutcome, ...]
    raw_score: Decimal
    max_score: Decimal
    algorithm_version: str = ALGORITHM_VERSION

    def count(self, reason: Reason) -> int:
        return sum(1 for item in self.items if item.reason == reason)


def _normalize_key(value: Any) -> str | None:
    if value is None:
        return None
    key = str(value).strip()
    return key or None


def score_single_choice(
    items_with_keys: Sequence[ScoringItem], answers: Mapping[UUID, str | None]
) -> ScoreBreakdown:
    """Score one attempt. Answers for items outside the exam are ignored.

    Raises ``ValueError`` for an unusable exam (no items, duplicate items, non-positive points
    or a missing key) instead of silently awarding zero.
    """
    if not items_with_keys:
        raise ValueError("exam has no items")
    seen: set[UUID] = set()
    outcomes: list[ItemOutcome] = []
    for item in items_with_keys:
        if item.item_id in seen:
            raise ValueError("duplicate item")
        seen.add(item.item_id)
        points = q2(item.points)
        if points <= 0:
            raise ValueError("item points must be positive")
        correct = _normalize_key(item.correct_key)
        if correct is None:
            raise ValueError("item has no answer key")
        selected = _normalize_key(answers.get(item.item_id))
        if selected is None:
            reason: Reason = "blank"
        elif item.choice_keys is not None and selected not in item.choice_keys:
            reason = "invalid_option"
        elif selected == correct:
            reason = "correct"
        else:
            reason = "incorrect"
        outcomes.append(
            ItemOutcome(
                item_id=item.item_id,
                selected_key=selected,
                answer_source="blank" if selected is None else "submitted",
                reason=reason,
                awarded_points=points if reason == "correct" else q2(0),
                max_points=points,
            )
        )
    raw = q2(sum((o.awarded_points for o in outcomes), Decimal(0)))
    total = q2(sum((o.max_points for o in outcomes), Decimal(0)))
    return ScoreBreakdown(tuple(outcomes), raw, total)


def snapshot_sha256(answers: Iterable[tuple[UUID, str | None]]) -> bytes:
    """Mirror of ``edu.attempt_snapshot_sha256``: ``<uuid>:<key>`` lines, LF, uuid order."""
    lines = [f"{item_id}:{key or ''}" for item_id, key in sorted(answers, key=lambda a: a[0])]
    return hashlib.sha256("\n".join(lines).encode()).digest()


def run_key(attempt_id: UUID, snapshot: bytes, algorithm_version: str = ALGORITHM_VERSION) -> str:
    """Idempotency key of a grading run: same attempt + snapshot + algorithm -> same result."""
    material = f"{attempt_id}:{snapshot.hex()}:{algorithm_version}"
    return hashlib.sha256(material.encode()).hexdigest()


def grading_status(attempt_status: str, has_current_grade: bool) -> GradingStatus:
    """``pending`` is never shown as zero: a submitted attempt without a grade is pending."""
    if attempt_status == "in_progress":
        return "not_submitted"
    if attempt_status == "void":
        return "void"
    return "graded" if has_current_grade else "pending"


def automatic_grade_action(
    current: tuple[UUID, str] | None, result_id: UUID
) -> Literal["insert", "noop", "keep_teacher"]:
    """What an automatic grading run does with the attempt's current grade.

    ``current`` is ``(grading_result_id, approval_mode)`` of the current revision. A replay of
    the same result is a no-op; a teacher override is never superseded automatically.
    """
    if current is None:
        return "insert"
    if current[0] == result_id:
        return "noop"
    if current[1] == "teacher":
        return "keep_teacher"
    return "insert"


def selected_key(response: Any) -> str | None:
    if isinstance(response, Mapping):
        return _normalize_key(response.get("selectedKey"))
    return None


def scoring_items(item_rows: Iterable[Any], key_rows: Iterable[Any]) -> list[ScoringItem]:
    """Join exam items (points, choices) with keys from ``edu.exam_keys_for_scoring``."""
    keys = {row[0]: row[1] for row in key_rows}
    items = []
    for row in item_rows:
        choices = row[2] or []
        choice_keys = frozenset(
            str(choice.get("key")).strip()
            for choice in choices
            if isinstance(choice, Mapping) and choice.get("key") is not None
        )
        items.append(ScoringItem(row[0], q2(row[1]), keys.get(row[0]), choice_keys or None))
    return items


class GradingRejected(Exception):
    """Permanent grading failure with a safe error code (no student data)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def next_revision(max_revision: int | None) -> int:
    return (max_revision or 0) + 1


def grade_attempt_job(db: Session, job: Any, now: datetime) -> dict[str, Any]:
    """Grade one submitted attempt in a single transaction (the caller's).

    Idempotent: the grading result is keyed by ``run_key`` (UNIQUE (attempt_id, run_key)), and
    a replay whose result is already current changes nothing. The attempt row is locked so
    grading serializes with a teacher override; the assignment row is share-locked so a
    concurrent score release is either seen (grade released now) or sees this grade.
    """
    try:
        attempt_id = UUID(str(job.input.get("attemptId")))
    except (AttributeError, TypeError, ValueError):
        raise GradingRejected("invalid_job_input") from None
    attempt = db.scalar(
        select(QuizAttempt)
        .where(QuizAttempt.id == attempt_id, QuizAttempt.workspace_id == job.workspace_id)
        .with_for_update()
    )
    if attempt is None:
        raise GradingRejected("attempt_not_found")
    if attempt.status == "void":
        return {"attemptId": str(attempt_id), "action": "skipped_void"}
    if attempt.status == "in_progress":
        raise GradingRejected("attempt_not_submitted")
    assignment = db.scalar(
        select(Assignment)
        .where(
            Assignment.workspace_id == attempt.workspace_id,
            Assignment.id == attempt.assignment_id,
        )
        .with_for_update(read=True)
    )
    if assignment is None:
        raise GradingRejected("assignment_not_found")
    item_rows = db.execute(
        select(exam_items_ref.c.id, exam_items_ref.c.points, exam_items_ref.c.choices).where(
            exam_items_ref.c.workspace_id == attempt.workspace_id,
            exam_items_ref.c.exam_version_id == attempt.exam_version_id,
        )
    ).all()
    key_rows = db.execute(
        text("SELECT exam_item_id, correct_key, points FROM edu.exam_keys_for_scoring(:version)"),
        {"version": attempt.exam_version_id},
    ).all()
    answer_rows = db.execute(
        select(StudentAnswer.exam_item_id, StudentAnswer.response).where(
            StudentAnswer.attempt_id == attempt.id
        )
    ).all()
    answers = {row[0]: selected_key(row[1]) for row in answer_rows}
    snapshot = snapshot_sha256(answers.items())
    stored = attempt.submitted_snapshot_sha256
    if stored is not None and bytes(stored) != snapshot:
        raise GradingRejected("snapshot_mismatch")
    try:
        breakdown = score_single_choice(scoring_items(item_rows, key_rows), answers)
    except ValueError:
        raise GradingRejected("answer_key_invalid") from None

    key = run_key(attempt.id, snapshot, breakdown.algorithm_version)
    result_id = db.scalar(
        select(GradingResult.id).where(
            GradingResult.attempt_id == attempt.id, GradingResult.run_key == key
        )
    )
    if result_id is None:
        result_id = uuid4()
        db.execute(
            insert(GradingResult).values(
                id=result_id,
                workspace_id=attempt.workspace_id,
                attempt_id=attempt.id,
                exam_version_id=attempt.exam_version_id,
                run_key=key,
                input_hash=snapshot.hex(),
                algorithm_version=breakdown.algorithm_version,
                source="online",
                raw_score=breakdown.raw_score,
                max_score=breakdown.max_score,
                status="approved",
                created_at=now,
            )
        )
        db.execute(
            insert(GradingResultItem),
            [
                {
                    "grading_result_id": result_id,
                    "workspace_id": attempt.workspace_id,
                    "exam_version_id": attempt.exam_version_id,
                    "exam_item_id": outcome.item_id,
                    "effective_response": outcome.effective_response,
                    "answer_source": outcome.answer_source,
                    "awarded_points": outcome.awarded_points,
                    "max_points": outcome.max_points,
                    "reason": outcome.reason,
                }
                for outcome in breakdown.items
            ],
        )
    current = db.execute(
        select(Grade.id, Grade.grading_result_id, Grade.approval_mode).where(
            Grade.attempt_id == attempt.id, Grade.is_current.is_(True)
        )
    ).first()
    action = automatic_grade_action(
        (current[1], current[2]) if current is not None else None, result_id
    )
    summary = {
        "attemptId": str(attempt.id),
        "gradingResultId": str(result_id),
        "score": str(breakdown.raw_score),
        "maxScore": str(breakdown.max_score),
        "action": action,
    }
    if action != "insert":
        return summary
    max_revision = db.scalar(
        select(func.max(Grade.revision_no)).where(Grade.attempt_id == attempt.id)
    )
    if current is not None:
        # Clear the old current flag first: the partial unique index is not deferrable.
        db.execute(update(Grade).where(Grade.id == current[0]).values(is_current=False))
    db.execute(
        insert(Grade).values(
            id=uuid4(),
            workspace_id=attempt.workspace_id,
            attempt_id=attempt.id,
            grading_result_id=result_id,
            revision_no=next_revision(max_revision),
            score=breakdown.raw_score,
            max_score=breakdown.max_score,
            is_current=True,
            approval_mode="automatic",
            approved_at=now,
            released_at=automatic_release_at(
                assignment.score_release, assignment.scores_released_at, now
            ),
        )
    )
    if attempt.status == "submitted":
        db.execute(
            update(QuizAttempt)
            .where(QuizAttempt.id == attempt.id)
            .values(status="graded", updated_at=now)
        )
    db.flush()
    return summary
