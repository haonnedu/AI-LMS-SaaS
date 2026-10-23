"""Fakes for the M4 AI/exam/export tests (no PostgreSQL, no S3, no network).

``GenFakeSession`` extends the authoring in-memory session with the exam key readers
(``edu.exam_item_key`` / ``edu.exam_item_explanation``), INSERT-only ``exam_answer_keys`` and
``begin_nested``. ``SyncSession`` adapts it to the synchronous worker API by driving the fake's
coroutines (which never suspend) to completion.
"""

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

from authoring_fakes import FakeSession, Rows
from sqlalchemy.sql.dml import Insert

from app.services.generation import run_sync


class GenFakeSession(FakeSession):
    def __init__(self):
        super().__init__()
        self.exam_keys: dict[UUID, tuple[str, str | None]] = {}
        self.exam_key_reads = 0

    @asynccontextmanager
    async def begin_nested(self):
        yield

    def _function(self, stmt):
        sql = str(stmt)
        if "edu.exam_item_key" in sql:
            self.exam_key_reads += 1
            params = list(stmt.compile().params.values())
            entry = self.exam_keys.get(params[0])
            return True, entry[0] if entry else None
        if "edu.exam_item_explanation" in sql:
            self.exam_key_reads += 1
            params = list(stmt.compile().params.values())
            entry = self.exam_keys.get(params[0])
            return True, entry[1] if entry else None
        return super()._function(stmt)

    async def execute(self, stmt, params=None):
        if isinstance(stmt, Insert) and stmt.table.name == "exam_answer_keys":
            self.statements.append(stmt)
            values = stmt.compile().params
            item = values["exam_item_id"]
            assert item not in self.exam_keys, "exam keys are insert-only"
            self.exam_keys[item] = (values["correct_key"], values["explanation"])
            return Rows()
        return await super().execute(stmt, params)


class SyncSession:
    """Synchronous facade (worker side) over ``GenFakeSession``."""

    def __init__(self, fake: GenFakeSession):
        self.fake = fake

    def add(self, obj):
        self.fake.add(obj)

    def flush(self):
        run_sync(self.fake.flush())

    def scalar(self, stmt, params=None):
        return run_sync(self.fake.scalar(stmt))

    def scalars(self, stmt, params=None):
        return run_sync(self.fake.scalars(stmt))

    def execute(self, stmt, params=None):
        return run_sync(self.fake.execute(stmt))

    @contextmanager
    def begin_nested(self):
        yield


class FakeStore:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key, body, *, mime, size, sha256):
        data = body.read()
        assert len(data) == size
        self.objects[key] = (data, mime)

    def presign_get(self, key, *, file_name, mime, ttl_seconds=60, now=None):
        from datetime import UTC, datetime, timedelta

        assert ttl_seconds <= 300
        return f"https://signed.example/{file_name}", datetime.now(UTC) + timedelta(
            seconds=ttl_seconds
        )


def job(workspace_id: UUID, user_id: UUID, kind: str = "content.generate", input=None):
    return SimpleNamespace(
        id=uuid4(),
        workspace_id=workspace_id,
        requested_by_user_id=user_id,
        kind=kind,
        input=input or {},
    )
