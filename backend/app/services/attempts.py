"""Student assignments and attempts (ASSIGN-02, ASMT-01/02/04/05): thin, typed wrappers around
the SECURITY DEFINER functions of migration 0014.

Students are not workspace members, so these calls run in a plain transaction with only the
verified identity applied (``current_user`` -> ``set_identity``); the database derives the
student from ``edu.actor_id()``. None of the result types below has an answer-key or
explanation field: keys only ever leave the database through ``edu.student_results`` after
the assignment's solutions are released.

Deterministic race outcomes (enforced in SQL by the attempt row lock + fresh
``clock_timestamp()``; ``decide_save``/``decide_submit`` mirror the rules for tests):

* autosave vs autosave: the second write must carry the newer ``clientSequence`` and the
  current ``expectedRevision``; an older or reordered write is rejected (EV014, 409
  ``stale_answer``) and never overwrites a newer answer. An exact retry of an already
  committed write is acknowledged without writing.
* autosave after expiry (``now > deadline_at + 5 s``): rejected (EV010, 409 ``attempt_expired``)
  and the frozen answer set is unchanged; after submission: EV015 (409 ``attempt_closed``).
* submit twice with the same key: the second returns the same status and snapshot
  (``replayed``); the same key with a different request is EV011 (409 ``idempotency_conflict``).
* submit vs deadline sweeper: whichever commits first finalizes the attempt; the other finds it
  no longer ``in_progress`` and is a no-op (the sweeper skips locked rows; a late submit
  returns the existing snapshot). A submit received after the grace finalizes with reason
  ``deadline`` and ``submitted_at = deadline_at``: only answers saved in time are graded.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.services.assessment_common import (
    ASSIGNMENT_NOT_FOUND,
    ATTEMPT_NOT_FOUND,
    GRACE,
    NotFound,
    map_db_error,
)
from app.services.jobs import request_hash

Availability = Literal["resume", "open", "not_open_yet", "closed", "limit_reached", "done"]


# ---- Pure mirrors of the SQL rules (documentation + deterministic tests) --------------------


def start_availability(
    *,
    status: str,
    class_active: bool,
    opens_at: datetime,
    closes_at: datetime | None,
    now: datetime,
    attempts_used: int,
    max_attempts: int,
    in_progress: bool,
) -> Availability:
    """What the student can do now (mirrors ``edu.student_start_attempt``)."""
    if in_progress:
        return "resume"
    if status != "published" or not class_active or (closes_at is not None and now >= closes_at):
        return "done" if attempts_used else "closed"
    if now < opens_at:
        return "not_open_yet"
    if attempts_used >= max_attempts:
        return "limit_reached"
    return "open"


@dataclass(frozen=True)
class StoredAnswer:
    selected_key: str | None
    answer_revision: int
    client_sequence: int


def decide_save(
    *,
    status: str,
    deadline_at: datetime | None,
    now: datetime,
    stored: StoredAnswer | None,
    selected_key: str | None,
    expected_revision: int,
    client_sequence: int,
) -> str:
    """Mirror of ``edu.student_save_answer``: ``ack`` | ``write`` | an error SQLSTATE."""
    if status != "in_progress":
        return "EV015"
    if deadline_at is not None and now > deadline_at + GRACE:
        return "EV010"
    if stored is None:
        return "write" if expected_revision == 0 else "EV014"
    if (
        client_sequence == stored.client_sequence
        and expected_revision == stored.answer_revision - 1
        and selected_key == stored.selected_key
    ):
        return "ack"
    if client_sequence <= stored.client_sequence or expected_revision != stored.answer_revision:
        return "EV014"
    return "write"


def decide_submit(
    *,
    status: str,
    deadline_at: datetime | None,
    now: datetime,
    stored_key: str | None,
    stored_hash: str | None,
    key: str,
    digest: str,
) -> str:
    """Mirror of ``edu.student_submit``: ``student`` | ``deadline`` (finalize) | ``replay``."""
    if status == "in_progress":
        return "deadline" if deadline_at is not None and now > deadline_at + GRACE else "student"
    if status == "void":
        return "EV015"
    if stored_key == key and stored_hash != digest:
        return "EV011"
    return "replay"


def effective_deadline(
    started_at: datetime, closes_at: datetime | None, time_limit_seconds: int | None
) -> datetime | None:
    """Earliest of ``closes_at`` and ``started_at + time limit``; None when both are absent."""
    bounds = [closes_at] if closes_at is not None else []
    if time_limit_seconds:
        bounds.append(started_at + timedelta(seconds=time_limit_seconds))
    return min(bounds) if bounds else None


def start_request_hash(assignment_id: UUID) -> str:
    return request_hash("attempt.start", {"assignmentId": str(assignment_id)})


def submit_request_hash(attempt_id: UUID) -> str:
    return request_hash("attempt.submit", {"attemptId": str(attempt_id)})


# ---- Result types (no key/explanation fields by construction) -------------------------------


@dataclass(frozen=True)
class StudentAssignment:
    assignment_id: UUID
    workspace_id: UUID
    class_id: UUID
    class_name: str
    title: str
    opens_at: datetime
    closes_at: datetime | None
    time_limit_seconds: int | None
    max_attempts: int
    timezone: str
    status: str
    attempts_used: int
    in_progress_attempt_id: UUID | None
    latest_attempt_id: UUID | None
    latest_attempt_status: str | None
    availability: Availability
    server_now: datetime
    instructions: str | None = None
    item_count: int | None = None
    total_points: Decimal | None = None


@dataclass(frozen=True)
class StartedAttempt:
    attempt_id: UUID
    created: bool
    status: str
    attempt_no: int
    started_at: datetime
    deadline_at: datetime | None
    server_now: datetime


@dataclass(frozen=True)
class AttemptItem:
    item_id: UUID
    position: int
    stem: str
    choices: list[dict[str, str]]
    points: Decimal
    selected_key: str | None
    answer_revision: int
    client_sequence: int
    saved_at: datetime | None


@dataclass(frozen=True)
class AttemptView:
    attempt_id: UUID
    assignment_id: UUID
    title: str
    attempt_no: int
    status: str
    started_at: datetime
    deadline_at: datetime | None
    submitted_at: datetime | None
    submission_reason: str | None
    snapshot_sha256: str | None
    answer_sequence: int
    server_now: datetime
    items: list[AttemptItem]


@dataclass(frozen=True)
class SavedAnswer:
    answer_revision: int
    saved_at: datetime
    server_now: datetime


@dataclass(frozen=True)
class Submission:
    status: str
    submitted_at: datetime
    snapshot_sha256: str
    submission_reason: str
    job_id: UUID | None
    replayed: bool


@dataclass(frozen=True)
class ExpiredAttempt:
    attempt_id: UUID
    workspace_id: UUID
    job_id: UUID | None


# ---- Calls ----------------------------------------------------------------------------------


async def _rows(
    db: AsyncSession, sql: str, params: dict[str, Any], not_found: tuple[str, str]
) -> Sequence[Any]:
    try:
        return (await db.execute(text(sql), params)).all()
    except DBAPIError as exc:
        mapped = map_db_error(exc, not_found=not_found)
        if mapped is exc:
            raise
        raise mapped from None


def _assignment(row: Any, detailed: bool = False) -> StudentAssignment:
    availability = start_availability(
        status=row.out_status,
        class_active=bool(row.out_class_active),
        opens_at=row.out_opens_at,
        closes_at=row.out_closes_at,
        now=row.out_server_now,
        attempts_used=row.out_attempts_used,
        max_attempts=row.out_max_attempts,
        in_progress=row.out_in_progress_attempt_id is not None,
    )
    return StudentAssignment(
        assignment_id=row.out_assignment_id,
        workspace_id=row.out_workspace_id,
        class_id=row.out_class_id,
        class_name=row.out_class_name,
        title=row.out_title,
        opens_at=row.out_opens_at,
        closes_at=row.out_closes_at,
        time_limit_seconds=row.out_time_limit_seconds,
        max_attempts=row.out_max_attempts,
        timezone=row.out_timezone,
        status=row.out_status,
        attempts_used=row.out_attempts_used,
        in_progress_attempt_id=row.out_in_progress_attempt_id,
        latest_attempt_id=row.out_latest_attempt_id,
        latest_attempt_status=row.out_latest_attempt_status,
        availability=availability,
        server_now=row.out_server_now,
        instructions=row.out_instructions if detailed else None,
        item_count=row.out_item_count if detailed else None,
        total_points=row.out_total_points if detailed else None,
    )


async def list_assignments(db: AsyncSession) -> list[StudentAssignment]:
    rows = await _rows(db, "SELECT * FROM edu.student_assignments()", {}, ASSIGNMENT_NOT_FOUND)
    return [_assignment(row) for row in rows]


async def assignment_detail(db: AsyncSession, assignment_id: UUID) -> StudentAssignment:
    rows = await _rows(
        db,
        "SELECT * FROM edu.student_assignment_detail(:assignment)",
        {"assignment": assignment_id},
        ASSIGNMENT_NOT_FOUND,
    )
    if not rows:
        raise NotFound(*ASSIGNMENT_NOT_FOUND)
    return _assignment(rows[0], detailed=True)


async def start_attempt(
    db: AsyncSession, assignment_id: UUID, idempotency_key: str
) -> StartedAttempt:
    rows = await _rows(
        db,
        "SELECT * FROM edu.student_start_attempt(:assignment, :key, :hash)",
        {
            "assignment": assignment_id,
            "key": idempotency_key,
            "hash": start_request_hash(assignment_id),
        },
        ASSIGNMENT_NOT_FOUND,
    )
    row = rows[0]
    return StartedAttempt(
        attempt_id=row.out_attempt_id,
        created=bool(row.out_created),
        status=row.out_status,
        attempt_no=row.out_attempt_no,
        started_at=row.out_started_at,
        deadline_at=row.out_deadline_at,
        server_now=row.out_server_now,
    )


async def attempt_view(db: AsyncSession, attempt_id: UUID) -> AttemptView:
    params = {"attempt": attempt_id}
    header = await _rows(
        db, "SELECT * FROM edu.student_attempt(:attempt)", params, ATTEMPT_NOT_FOUND
    )
    if not header:
        raise NotFound(*ATTEMPT_NOT_FOUND)
    h = header[0]
    items = await _rows(
        db, "SELECT * FROM edu.student_attempt_items(:attempt)", params, ATTEMPT_NOT_FOUND
    )
    return AttemptView(
        attempt_id=h.out_attempt_id,
        assignment_id=h.out_assignment_id,
        title=h.out_title,
        attempt_no=h.out_attempt_no,
        status=h.out_status,
        started_at=h.out_started_at,
        deadline_at=h.out_deadline_at,
        submitted_at=h.out_submitted_at,
        submission_reason=h.out_submission_reason,
        snapshot_sha256=bytes(h.out_snapshot_sha256).hex() if h.out_snapshot_sha256 else None,
        answer_sequence=h.out_answer_sequence,
        server_now=h.out_server_now,
        items=[
            AttemptItem(
                item_id=i.out_item_id,
                position=i.out_position,
                stem=i.out_stem,
                choices=[
                    {"key": str(c.get("key")), "text": str(c.get("text") or "")}
                    for c in (i.out_choices or [])
                    if isinstance(c, dict)
                ],
                points=i.out_points,
                selected_key=i.out_selected_key,
                answer_revision=i.out_answer_revision,
                client_sequence=i.out_client_sequence,
                saved_at=i.out_saved_at,
            )
            for i in items
        ],
    )


async def save_answer(
    db: AsyncSession,
    attempt_id: UUID,
    item_id: UUID,
    *,
    selected_key: str | None,
    expected_revision: int,
    client_sequence: int,
) -> SavedAnswer:
    rows = await _rows(
        db,
        "SELECT * FROM edu.student_save_answer(:attempt, :item, :key, :expected, :sequence)",
        {
            "attempt": attempt_id,
            "item": item_id,
            "key": selected_key,
            "expected": expected_revision,
            "sequence": client_sequence,
        },
        ATTEMPT_NOT_FOUND,
    )
    row = rows[0]
    return SavedAnswer(row.out_answer_revision, row.out_saved_at, row.out_server_now)


async def submit(db: AsyncSession, attempt_id: UUID, idempotency_key: str) -> Submission:
    rows = await _rows(
        db,
        "SELECT * FROM edu.student_submit(:attempt, :key, :hash)",
        {
            "attempt": attempt_id,
            "key": idempotency_key,
            "hash": submit_request_hash(attempt_id),
        },
        ATTEMPT_NOT_FOUND,
    )
    row = rows[0]
    return Submission(
        status=row.out_status,
        submitted_at=row.out_submitted_at,
        snapshot_sha256=bytes(row.out_snapshot_sha256).hex(),
        submission_reason=row.out_submission_reason,
        job_id=row.out_job_id,
        replayed=bool(row.out_replayed),
    )


async def results(db: AsyncSession, attempt_id: UUID) -> dict[str, Any]:
    rows = await _rows(
        db,
        "SELECT edu.student_results(:attempt) AS out_results",
        {"attempt": attempt_id},
        ATTEMPT_NOT_FOUND,
    )
    return rows[0].out_results


def expire_due(db: Session, now: datetime) -> list[ExpiredAttempt]:
    """Deadline sweeper step (cross-tenant definer function; returns ids only)."""
    rows = db.execute(
        text("SELECT out_attempt_id, out_workspace_id, out_job_id FROM edu.expire_attempts(:now)"),
        {"now": now},
    ).all()
    return [ExpiredAttempt(row[0], row[1], row[2]) for row in rows]
