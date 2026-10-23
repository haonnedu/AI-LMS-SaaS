"""Embedding stage of the ingest pipeline (KNOW-06). Worker-side, synchronous session, RLS
context already set for the job's workspace.

For one document version: select chunks not yet embedded with the configured
``(model, version)`` (idempotent: already-current chunks are skipped), reserve usage units
(1 unit per started 1000 estimated tokens), record an ``embedding_runs`` row, embed in batches
of at most 64 texts and write ``embedding/embedding_model/embedding_version`` (the only chunk
columns the database lets the runtime role update). Provider failures never raise: the run is
marked ``failed`` with a safe code and the units actually consumed (retries included) stay on
the ledger. ``embed_version_safely`` additionally isolates unexpected database errors in a
savepoint so an embedding problem can never undo activation of the text version.

Trade-off (pilot): provider calls happen inside the job transaction, which keeps the document
row lock for the duration; batches are bounded and the stage can be retried on its own with a
``document.embed`` job.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.jobs import UsageEvent, WorkspaceQuota
from app.models.knowledge import EmbeddingRun
from app.services import embeddings, usage

logger = logging.getLogger("eduvia.indexing")

UNIT_TYPE = "embedding_ktok"
OVERAGE_KIND = "embedding_overage"

STALE_CHUNKS_SQL = """
SELECT c.id, c.text, c.token_estimate
FROM edu.document_chunks c
WHERE c.workspace_id = :workspace_id
  AND c.document_version_id = :version_id
  AND (c.embedding IS NULL
       OR c.embedding_model IS DISTINCT FROM :model
       OR c.embedding_version IS DISTINCT FROM :model_version)
ORDER BY c.chunk_index
"""

WRITE_VECTOR_SQL = """
UPDATE edu.document_chunks
SET embedding = CAST(:embedding AS vector),
    embedding_model = :model,
    embedding_version = :model_version
WHERE workspace_id = :workspace_id AND id = :chunk_id
"""


def stale_chunks(db: Session, workspace_id: UUID, version_id: UUID, model: str, version: str):
    return list(
        db.execute(
            text(STALE_CHUNKS_SQL),
            {
                "workspace_id": workspace_id,
                "version_id": version_id,
                "model": model,
                "model_version": version,
            },
        ).all()
    )


def reserve_units(
    db: Session, workspace_id: UUID, units: int, *, job_id: UUID | None, now: datetime
) -> bool:
    """Sync twin of ``usage.reserve``: lock the quota row, check the monthly cap, append."""
    if units <= 0:
        raise ValueError("Reservations must be positive")
    quota = db.scalar(
        select(WorkspaceQuota).where(WorkspaceQuota.workspace_id == workspace_id).with_for_update()
    )
    cap = quota.month_cap_units if quota is not None else 0
    used = db.scalar(
        select(func.coalesce(func.sum(UsageEvent.units), 0)).where(
            UsageEvent.workspace_id == workspace_id,
            UsageEvent.created_at >= usage.month_start(now),
        )
    )
    if not usage.within_cap(int(used or 0), cap, units):
        return False
    record_usage(db, workspace_id, "reservation", units, job_id=job_id, now=now)
    return True


def record_usage(
    db: Session, workspace_id: UUID, kind: str, units: int, *, job_id: UUID | None, now: datetime
) -> None:
    db.add(
        UsageEvent(
            id=uuid4(),
            workspace_id=workspace_id,
            job_id=job_id,
            kind=kind,
            units=units,
            unit_type=UNIT_TYPE,
            created_at=now,
        )
    )
    db.flush()


def _finish(run: EmbeddingRun, status: str, now: datetime, code: str | None = None) -> None:
    run.status = status
    run.error_code = code[:64] if code else None
    run.finished_at = now


def summary(run: EmbeddingRun | None, *, model: str, version: str) -> dict[str, Any]:
    if run is None:
        return {"status": "current", "model": model, "version": version, "chunks": 0}
    return {
        "runId": str(run.id),
        "status": run.status,
        "model": run.model,
        "version": run.version,
        "chunks": run.chunk_count,
        "units": run.units,
        "errorCode": run.error_code,
    }


def embed_version(
    db: Session,
    *,
    workspace_id: UUID,
    version_id: UUID,
    embedder: embeddings.EmbeddingProvider,
    job_id: UUID | None,
    now: datetime,
) -> dict[str, Any]:
    model, version = embedder.model, embedder.version
    rows = stale_chunks(db, workspace_id, version_id, model, version)
    if not rows:
        return summary(None, model=model, version=version)
    estimated = embeddings.units_for_tokens(sum(int(row.token_estimate) for row in rows))
    run = EmbeddingRun(
        id=uuid4(),
        workspace_id=workspace_id,
        document_version_id=version_id,
        job_id=job_id,
        model=model,
        version=version,
        status="pending",
        chunk_count=len(rows),
        units=0,
        provider_request_ids=[],
        created_at=now,
    )
    db.add(run)
    db.flush()
    if not reserve_units(db, workspace_id, estimated, job_id=job_id, now=now):
        _finish(run, "failed", now, "quota_exceeded")
        db.flush()
        return summary(run, model=model, version=version)

    units = 0
    request_ids: list[str] = []
    try:
        for start in range(0, len(rows), embeddings.MAX_BATCH):
            batch = rows[start : start + embeddings.MAX_BATCH]
            result = embedder.embed([row.text for row in batch])
            units += result.units
            request_ids.extend(
                result.request_ids or ([result.request_id] if result.request_id else [])
            )
            if (
                len(result.vectors) != len(batch)
                or result.model != model
                or result.version != version
                or any(len(vector) != embedder.dimension for vector in result.vectors)
            ):
                raise embeddings.EmbeddingError("provider_bad_response")
            db.execute(
                text(WRITE_VECTOR_SQL),
                [
                    {
                        "embedding": embeddings.vector_literal(vector),
                        "model": model,
                        "model_version": version,
                        "workspace_id": workspace_id,
                        "chunk_id": row.id,
                    }
                    for row, vector in zip(batch, result.vectors, strict=True)
                ],
            )
    except embeddings.EmbeddingError as exc:
        units += exc.units
        request_ids.extend(exc.request_ids)
        _finish(run, "failed", now, exc.code)
        logger.warning("embedding_run_failed", extra={"error_code": exc.code})
    else:
        _finish(run, "succeeded", now)
    run.units = units
    run.provider_request_ids = request_ids[:200]
    if units > estimated:  # retries/rounding cost more than reserved: keep the ledger honest
        record_usage(db, workspace_id, OVERAGE_KIND, units - estimated, job_id=job_id, now=now)
    db.flush()
    return summary(run, model=model, version=version)


def embed_version_safely(db: Session, **kwargs) -> dict[str, Any]:
    """Ingest-time wrapper: any unexpected error is rolled back to a savepoint and reported,
    so the already-activated text version is never lost because of the embedding stage."""
    try:
        with db.begin_nested():
            return embed_version(db, **kwargs)
    except Exception as exc:
        logger.warning("embedding_stage_failed", extra={"error_type": type(exc).__name__})
        return {"status": "failed", "errorCode": "embedding_stage_error"}
