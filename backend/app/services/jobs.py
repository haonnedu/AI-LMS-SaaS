"""Lean durable jobs (JOB-01/JOB-02 lean): ``background_jobs`` is the source of truth.

Celery only carries job IDs. Every stage write is keyed by ``(job_id, attempt)`` so a
redelivered or stale message cannot overwrite a newer attempt, and a sweeper recovers
expired leases and queued jobs whose broker message may have been lost.
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.identity import ApiError
from app.models.jobs import BackgroundJob

logger = logging.getLogger("eduvia.jobs")

LEASE = timedelta(minutes=5)
DISPATCH_TIMEOUT = timedelta(minutes=10)
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled"}),
    # running -> queued is a retry after a transient failure or an expired lease.
    "running": frozenset({"succeeded", "failed", "queued", "cancelled"}),
    # failed -> queued is an explicit user retry.
    "failed": frozenset({"queued"}),
    "succeeded": frozenset(),
    "cancelled": frozenset(),
}
QUEUE_BY_KIND = {
    "document.ingest": "ingestion",
    "document.delete": "ingestion",
    "document.reingest": "ingestion",
    "document.embed": "ingestion",
    "content.generate": "generation",
    "questions.generate": "generation",
    "export.render": "export",
    "attempt.grade": "default",
    "privacy.export": "default",
    "privacy.erase": "default",
}
CLIENT_KEY_PREFIX = "client:"
SYSTEM_KEY_PREFIX = "system:"


class InvalidTransition(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def transition(job: BackgroundJob, to: str, *, now: datetime | None = None) -> BackgroundJob:
    if to not in ALLOWED_TRANSITIONS.get(job.status, frozenset()):
        raise InvalidTransition(f"{job.status} -> {to}")
    now = now or utcnow()
    job.status = to
    job.updated_at = now
    if to in TERMINAL:
        job.finished_at = now
        job.lease_expires_at = None
    elif to == "queued":
        job.lease_expires_at = None
        job.finished_at = None
    return job


def request_hash(kind: str, payload: Any) -> str:
    """Stable fingerprint of what the client asked for (canonical JSON, SHA-256)."""
    canonical = json.dumps(
        {"kind": kind, "payload": payload}, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def client_idempotency_key(raw: str | None) -> str:
    """Namespace client keys so they can never collide with server-derived system keys."""
    if raw is None:
        return CLIENT_KEY_PREFIX + str(uuid4())
    if not 1 <= len(raw) <= 128 or not raw.isascii() or not raw.isprintable():
        raise ApiError(422, "invalid_idempotency_key", "Idempotency-Key không hợp lệ.")
    return CLIENT_KEY_PREFIX + raw


def new_job(
    scope, kind: str, payload: dict[str, Any], key: str, digest: str, now: datetime
) -> BackgroundJob:
    return BackgroundJob(
        id=uuid4(),
        workspace_id=scope.workspace.id,
        requested_by_user_id=scope.user.id,
        kind=kind,
        status="queued",
        idempotency_key=key,
        request_hash=digest,
        attempt=0,
        max_attempts=3,
        cancel_requested=False,
        input=payload,
        created_at=now,
        updated_at=now,
    )


def _same_request(existing: BackgroundJob, digest: str) -> BackgroundJob:
    if existing.request_hash != digest:
        raise ApiError(
            409,
            "idempotency_conflict",
            "Idempotency-Key đã được dùng cho một yêu cầu khác.",
        )
    return existing


async def find_job_by_key(db: AsyncSession, scope, key: str) -> BackgroundJob | None:
    return await db.scalar(
        select(BackgroundJob).where(
            BackgroundJob.workspace_id == scope.workspace.id,
            BackgroundJob.requested_by_user_id == scope.user.id,
            BackgroundJob.idempotency_key == key,
        )
    )


async def enqueue_job(
    db: AsyncSession,
    scope,
    kind: str,
    input: dict[str, Any],
    idempotency_key: str,
    *,
    digest: str | None = None,
) -> tuple[BackgroundJob, bool]:
    """Insert a queued job or return the existing one; ``(job, created)``.

    Must run inside ``workspace_transaction``. Same key + same request returns the original
    job; same key + different request raises 409. A concurrent duplicate is caught by the
    unique constraint inside a savepoint, so the outer transaction stays usable.
    """
    digest = digest or request_hash(kind, input)
    existing = await find_job_by_key(db, scope, idempotency_key)
    if existing is not None:
        return _same_request(existing, digest), False
    job = new_job(scope, kind, input, idempotency_key, digest, utcnow())
    try:
        async with db.begin_nested():
            db.add(job)
            await db.flush()
    except IntegrityError:
        existing = await find_job_by_key(db, scope, idempotency_key)
        if existing is None:
            raise
        return _same_request(existing, digest), False
    return job, True


def request_cancel(job: BackgroundJob, now: datetime | None = None) -> bool:
    """Queued jobs cancel at once; running jobs stop at the next stage boundary.

    Returns False when nothing changed (already cancelled/requested): repeat calls are no-ops.
    """
    if job.status == "queued":
        transition(job, "cancelled", now=now)
        job.cancel_requested = True
        return True
    if job.status == "running":
        if job.cancel_requested:
            return False
        job.cancel_requested = True
        job.updated_at = now or utcnow()
        return True
    if job.status == "cancelled":
        return False
    raise ApiError(409, "job_not_cancellable", "Không thể hủy tác vụ đã kết thúc.")


def request_retry(job: BackgroundJob, now: datetime | None = None) -> bool:
    """Only failed jobs retry; a job already re-queued or running is returned unchanged."""
    if job.status == "failed":
        transition(job, "queued", now=now)
        job.attempt = 0
        job.error_code = None
        job.result = None
        job.cancel_requested = False
        return True
    if job.status in {"queued", "running"}:
        return False
    raise ApiError(409, "job_not_retryable", "Chỉ có thể thử lại tác vụ bị lỗi.")


# ---- worker side (sync session, RLS context already set for the job's workspace) ----


def apply_claim(job: BackgroundJob, now: datetime, lease: timedelta = LEASE) -> int | None:
    """Claim a queued job or reclaim an expired lease; returns the claimed attempt."""
    if job.status == "queued":
        if job.cancel_requested:
            transition(job, "cancelled", now=now)
            return None
        if job.attempt >= job.max_attempts:
            transition(job, "running", now=now)
            job.error_code = "max_attempts_exceeded"
            transition(job, "failed", now=now)
            return None
    elif job.status == "running" and job.lease_expires_at and job.lease_expires_at < now:
        if job.cancel_requested:
            transition(job, "cancelled", now=now)
            return None
        if job.attempt >= job.max_attempts:
            job.error_code = "lease_expired"
            transition(job, "failed", now=now)
            return None
    else:
        return None
    if job.status == "queued":
        transition(job, "running", now=now)
    job.attempt += 1
    job.started_at = job.started_at or now
    job.lease_expires_at = now + lease
    job.updated_at = now
    return job.attempt


def _locked(db: Session, job_id: UUID) -> BackgroundJob | None:
    return db.get(BackgroundJob, job_id, with_for_update=True, populate_existing=True)


def claim_job(db: Session, job_id: UUID, now: datetime | None = None) -> int | None:
    job = _locked(db, job_id)
    if job is None:
        return None
    attempt = apply_claim(job, now or utcnow())
    db.flush()
    return attempt


def running_attempt(db: Session, job_id: UUID, attempt: int) -> BackgroundJob | None:
    """Fence: the job row only if it is still running *this* attempt."""
    job = _locked(db, job_id)
    if job is None or job.status != "running" or job.attempt != attempt:
        return None
    return job


def complete_job(
    db: Session, job_id: UUID, attempt: int, result: dict[str, Any], now: datetime | None = None
) -> bool:
    job = running_attempt(db, job_id, attempt)
    if job is None:
        return False  # duplicate delivery or stale attempt: idempotent no-op
    job.result = result
    job.error_code = None
    transition(job, "succeeded", now=now)
    db.flush()
    return True


def cancel_running(db: Session, job_id: UUID, attempt: int, now: datetime | None = None) -> bool:
    job = running_attempt(db, job_id, attempt)
    if job is None or not job.cancel_requested:
        return False
    transition(job, "cancelled", now=now)
    db.flush()
    return True


def fail_job(
    db: Session,
    job_id: UUID,
    attempt: int,
    error_code: str,
    *,
    retryable: bool,
    now: datetime | None = None,
) -> str | None:
    """Returns 'queued' (will retry), 'failed', or None for a stale/duplicate write."""
    job = running_attempt(db, job_id, attempt)
    if job is None:
        return None
    job.error_code = error_code[:64]
    to = "queued" if retryable and job.attempt < job.max_attempts else "failed"
    transition(job, to, now=now)
    db.flush()
    return to


@dataclass(frozen=True)
class SweepOutcome:
    job_id: UUID
    action: str  # requeued | redispatch | failed | cancelled


def decide_sweep(
    job: BackgroundJob, now: datetime, dispatch_timeout: timedelta = DISPATCH_TIMEOUT
) -> str | None:
    if job.status == "running" and job.lease_expires_at and job.lease_expires_at < now:
        if job.cancel_requested:
            return "cancelled"
        return "failed" if job.attempt >= job.max_attempts else "requeued"
    if job.status == "queued" and job.updated_at < now - dispatch_timeout:
        return "cancelled" if job.cancel_requested else "redispatch"
    return None


def apply_sweep(job: BackgroundJob, action: str, now: datetime) -> None:
    if action == "requeued":
        job.error_code = "lease_expired"
        transition(job, "queued", now=now)
    elif action == "failed":
        job.error_code = "lease_expired"
        transition(job, "failed", now=now)
    elif action == "cancelled":
        transition(job, "cancelled", now=now)
    elif action == "redispatch":
        job.updated_at = now


def sweep_overdue(
    db: Session,
    now: datetime | None = None,
    *,
    job_ids: list[UUID] | None = None,
    dispatch_timeout: timedelta = DISPATCH_TIMEOUT,
    limit: int = 100,
) -> list[SweepOutcome]:
    """Re-queue or fail jobs whose lease expired; re-dispatch stale queued jobs.

    Only jobs visible under the current RLS context are touched. Rows locked by a live
    worker are skipped rather than waited on.
    """
    now = now or utcnow()
    query = (
        select(BackgroundJob)
        .where(
            or_(
                and_(BackgroundJob.status == "running", BackgroundJob.lease_expires_at < now),
                and_(
                    BackgroundJob.status == "queued",
                    BackgroundJob.updated_at < now - dispatch_timeout,
                ),
            )
        )
        .order_by(BackgroundJob.updated_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    if job_ids is not None:
        query = query.where(BackgroundJob.id.in_(job_ids))
    outcomes = []
    for job in db.scalars(query):
        action = decide_sweep(job, now, dispatch_timeout)
        if action is None:
            continue
        apply_sweep(job, action, now)
        outcomes.append(SweepOutcome(job.id, action))
    db.flush()
    return outcomes


# ---- dispatch (best effort; the sweeper re-dispatches queued jobs whose message was lost) ----


def send_job(job_id: UUID, kind: str, countdown: int | None = None) -> None:
    from app.worker import celery_app

    celery_app.send_task(
        "app.tasks.jobs.run",
        args=[str(job_id)],
        queue=QUEUE_BY_KIND.get(kind, "default"),
        countdown=countdown,
        retry=False,
    )


async def dispatch_job(job: BackgroundJob) -> bool:
    """Called after commit. A broker failure leaves the job queued for the sweeper."""
    try:
        await asyncio.to_thread(send_job, job.id, job.kind)
        return True
    except Exception as exc:
        logger.warning("job_dispatch_failed", extra={"error_type": type(exc).__name__})
        return False
