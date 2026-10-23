"""Monthly cap arithmetic and lock-serialized reservations (fake FOR UPDATE, no DB)."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.identity import ApiError
from app.models.jobs import UsageEvent
from app.services import usage

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "size,units",
    [(1, 1), (usage.MIB - 1, 1), (usage.MIB, 1), (usage.MIB + 1, 2), (25 * usage.MIB, 25)],
)
def test_units_per_started_mib(size, units):
    assert usage.units_for_bytes(size) == units


def test_month_start_is_utc():
    assert usage.month_start(NOW) == datetime(2026, 10, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "used,cap,units,ok",
    [(0, 10, 10, True), (9, 10, 1, True), (10, 10, 1, False), (5, 10, 6, False), (0, 0, 1, False)],
)
def test_within_cap(used, cap, units, ok):
    assert usage.within_cap(used, cap, units) is ok


class Ledger:
    """Shared committed state; the quota row lock is an asyncio.Lock."""

    def __init__(self, cap: int, used: int, honour_lock: bool = True):
        self.quota = SimpleNamespace(month_cap_units=cap)
        self.events = [SimpleNamespace(units=used, created_at=NOW)]
        self.lock = asyncio.Lock()
        self.honour_lock = honour_lock


class FakeTx:
    def __init__(self, ledger: Ledger):
        self.ledger, self.pending, self.locked = ledger, [], False

    async def scalar(self, stmt):
        await asyncio.sleep(0)  # let the other transaction interleave
        if getattr(stmt, "_for_update_arg", None) is not None:
            if self.ledger.honour_lock:
                await self.ledger.lock.acquire()
                self.locked = True
            return self.ledger.quota
        return sum(e.units for e in self.ledger.events + self.pending)

    def add(self, event):
        assert isinstance(event, UsageEvent)
        self.pending.append(event)

    async def flush(self):
        await asyncio.sleep(0)

    async def finish(self, commit: bool):
        if commit:
            self.ledger.events.extend(self.pending)
        if self.locked:
            self.ledger.lock.release()


async def reserve_in_tx(ledger, scope, units):
    tx = FakeTx(ledger)
    try:
        await usage.reserve(tx, scope, units, now=NOW)
        await asyncio.sleep(0.01)  # hold the lock across other work in the transaction
    except ApiError as exc:
        await tx.finish(commit=False)
        return exc.code
    await tx.finish(commit=True)
    return "ok"


SCOPE = SimpleNamespace(workspace=SimpleNamespace(id=uuid4()))


async def test_concurrent_reservations_cannot_exceed_cap():
    ledger = Ledger(cap=10, used=9)
    results = await asyncio.gather(*(reserve_in_tx(ledger, SCOPE, 1) for _ in range(2)))
    assert sorted(results) == ["ok", "quota_exceeded"]
    assert sum(e.units for e in ledger.events) == 10


async def test_without_row_lock_the_race_overshoots():
    """Control: proves the test above depends on the FOR UPDATE serialization."""
    ledger = Ledger(cap=10, used=9, honour_lock=False)
    results = await asyncio.gather(*(reserve_in_tx(ledger, SCOPE, 1) for _ in range(2)))
    assert results == ["ok", "ok"]


async def test_reservation_event_shape_and_missing_quota_denies():
    ledger = Ledger(cap=5, used=0)
    tx = FakeTx(ledger)
    job_id = uuid4()
    event = await usage.reserve(tx, SCOPE, 3, job_id=job_id, now=NOW)
    await tx.finish(commit=True)
    assert (event.kind, event.units, event.unit_type, event.job_id) == (
        "reservation",
        3,
        "upload_mib",
        job_id,
    )
    ledger.quota = None
    with pytest.raises(ApiError) as error:
        await usage.reserve(FakeTx(ledger), SCOPE, 1, now=NOW)
    assert (error.value.status, error.value.code) == (429, "quota_exceeded")


async def test_record_is_append_only_and_validated():
    tx = FakeTx(Ledger(cap=1, used=0))
    with pytest.raises(ValueError):
        await usage.record(tx, uuid4(), kind="reservation", units=-1, unit_type="upload_mib")
    with pytest.raises(ValueError):
        await usage.record(
            tx, uuid4(), kind="provider", units=0, unit_type="tokens", provider_cost_minor=-1
        )
    release = await usage.record(tx, uuid4(), kind="release", units=-2, unit_type="upload_mib")
    assert release.units == -2 and len(tx.pending) == 1
    with pytest.raises(ValueError):
        await usage.reserve(tx, SCOPE, 0)
