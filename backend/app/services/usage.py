"""Lean usage control (COST-01 lean): per-job reservation against a hard monthly cap.

The ledger (``usage_events``) is append-only and authoritative. A reservation locks the
workspace's quota row (``SELECT ... FOR UPDATE``), sums this month's units and inserts a
``reservation`` event in the same transaction, so concurrent reservations serialize and
can never exceed the cap together.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity import ApiError
from app.models.jobs import UsageEvent, WorkspaceQuota

MIB = 1024 * 1024
UPLOAD_UNIT_TYPE = "upload_mib"


def units_for_bytes(size_bytes: int) -> int:
    """One unit per started MiB; an upload always costs at least one unit."""
    return max(1, -(-size_bytes // MIB))


def month_start(now: datetime) -> datetime:
    now = now.astimezone(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def within_cap(used: int, cap: int, units: int) -> bool:
    return units >= 0 and used + units <= cap


async def used_units(db: AsyncSession, workspace_id: UUID, since: datetime) -> int:
    total = await db.scalar(
        select(func.coalesce(func.sum(UsageEvent.units), 0)).where(
            UsageEvent.workspace_id == workspace_id, UsageEvent.created_at >= since
        )
    )
    return int(total or 0)


async def reserve(
    db: AsyncSession,
    scope,
    units: int,
    *,
    job_id: UUID | None = None,
    unit_type: str = UPLOAD_UNIT_TYPE,
    now: datetime | None = None,
) -> UsageEvent:
    """Reserve ``units`` this month or raise 429 ``quota_exceeded``; inside the tenant tx."""
    if units <= 0:
        raise ValueError("Reservations must be positive")
    now = now or datetime.now(UTC)
    quota = await db.scalar(
        select(WorkspaceQuota)
        .where(WorkspaceQuota.workspace_id == scope.workspace.id)
        .with_for_update()
    )
    cap = quota.month_cap_units if quota is not None else 0
    used = await used_units(db, scope.workspace.id, month_start(now))
    if not within_cap(used, cap, units):
        raise ApiError(
            429,
            "quota_exceeded",
            "Không gian làm việc đã dùng hết hạn mức tháng này.",
        )
    return await record(
        db,
        scope.workspace.id,
        kind="reservation",
        units=units,
        unit_type=unit_type,
        job_id=job_id,
        now=now,
    )


async def record(
    db: AsyncSession,
    workspace_id: UUID,
    *,
    kind: str,
    units: int,
    unit_type: str,
    job_id: UUID | None = None,
    provider_cost_minor: int | None = None,
    now: datetime | None = None,
) -> UsageEvent:
    """Append one ledger event. Never updates or deletes; corrections are new events."""
    if units < 0 and kind != "release":
        raise ValueError("Only release events may carry negative units")
    if provider_cost_minor is not None and provider_cost_minor < 0:
        raise ValueError("Provider cost cannot be negative")
    event = UsageEvent(
        id=uuid4(),
        workspace_id=workspace_id,
        job_id=job_id,
        kind=kind,
        units=units,
        unit_type=unit_type,
        provider_cost_minor=provider_cost_minor,
        created_at=now or datetime.now(UTC),
    )
    db.add(event)
    await db.flush()
    return event
