"""Durable job execution. Messages carry only a job ID; the row in PostgreSQL is the truth.

Flow per delivery (acks_late, so a killed worker gets the message redelivered):
1. resolve the persisted actor (``edu.job_actor``), set RLS context, claim with a lease;
2. in a second transaction: fence on (job_id, attempt), honour ``cancel_requested``,
   run the handler and record completion atomically with its domain writes;
3. on error: fence again and either re-queue (bounded attempts) or fail.
A duplicate or stale delivery finds no claimable attempt and is a no-op.
"""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.infrastructure.sync_database import get_sync_sessionmaker, set_actor_context
from app.models.documents import Document
from app.models.jobs import BackgroundJob
from app.services import (
    attempts,
    embeddings,
    exports,
    generation,
    indexing,
    knowledge,
    parsing,
    releases,
    scoring,
)
from app.services import jobs as job_service
from app.services import llm as llm_service
from app.services.storage import ObjectStore, ObjectTooLarge
from app.worker import celery_app

logger = logging.getLogger("eduvia.worker")


class PermanentJobError(Exception):
    """Non-retryable failure with a safe, client-visible error code."""

    def __init__(self, code: str, rejection: knowledge.IngestRejected | None = None):
        super().__init__(code)
        self.code = code
        self.rejection = rejection


@dataclass
class HandlerContext:
    db: Session
    job: BackgroundJob
    store: ObjectStore
    now: datetime | None = None
    max_bytes: int | None = None
    embedder: embeddings.EmbeddingProvider | None = None
    llm: llm_service.LLMProvider | None = None

    def clock(self) -> datetime:
        return self.now or job_service.utcnow()

    def embedding_provider(self) -> embeddings.EmbeddingProvider:
        return self.embedder or default_embedder()

    def byte_limit(self) -> int:
        return self.max_bytes or get_settings().upload_max_bytes

    def llm_provider(self) -> llm_service.LLMProvider:
        return self.llm or default_llm()


@dataclass(frozen=True)
class Handler:
    run: Callable[[HandlerContext], dict[str, Any]]
    on_permanent_failure: Callable[[HandlerContext, Exception], None] | None = None


def _document(ctx: HandlerContext) -> Document | None:
    try:
        document_id = UUID(str(ctx.job.input.get("documentId")))
    except ValueError:
        raise PermanentJobError("invalid_job_input") from None
    document = ctx.db.get(Document, document_id, with_for_update=True)
    if document is not None and document.workspace_id != ctx.job.workspace_id:
        raise PermanentJobError("invalid_job_input")
    return document


def _download(ctx: HandlerContext, document: Document) -> bytes:
    """Bounded download, then integrity check against the checksum recorded at upload."""
    try:
        data = ctx.store.get_bytes(document.object_key, max_bytes=ctx.byte_limit())
    except ObjectTooLarge:
        raise PermanentJobError("object_size_mismatch") from None
    if len(data) != document.size_bytes:
        raise PermanentJobError("object_size_mismatch")
    if hashlib.sha256(data).digest() != bytes(document.sha256):
        raise PermanentJobError("object_checksum_mismatch")
    return data


def _index(ctx: HandlerContext, document: Document, mode: knowledge.Mode) -> dict[str, Any]:
    if not document.rights_attested:
        raise PermanentJobError("rights_attestation_required")
    data = _download(ctx, document)
    try:
        result = knowledge.ingest_bytes(
            ctx.db, document, data, mode=mode, max_bytes=ctx.byte_limit(), now=ctx.clock()
        )
    except knowledge.IngestRejected as exc:
        raise PermanentJobError(exc.code, rejection=exc) from None
    # KNOW-06: the text version is already active; an embedding failure is recorded on its
    # embedding run (retry with ``document.embed``) and never fails or undoes activation.
    result["embedding"] = indexing.embed_version_safely(
        ctx.db,
        workspace_id=document.workspace_id,
        version_id=UUID(result["versionId"]),
        embedder=ctx.embedding_provider(),
        job_id=ctx.job.id,
        now=ctx.clock(),
    )
    return result


def ingest_document(ctx: HandlerContext) -> dict[str, Any]:
    """Verify the stored object, then parse/chunk into a new immutable version and activate it
    atomically. Types without a registered parser are only published (lean behaviour)."""
    document = _document(ctx)
    if document is None or document.status == "deleted":
        return {"pages": None, "skipped": True}
    head = ctx.store.head(document.object_key)
    if head is None:
        raise PermanentJobError("object_missing")
    if int(head.get("ContentLength", -1)) != document.size_bytes:
        raise PermanentJobError("object_size_mismatch")
    if parsing.parser_for(document.mime_type) is None:
        document.status = "uploaded"
        ctx.db.flush()
        return {"pages": None}
    return _index(ctx, document, "ingest")


def reingest_document(ctx: HandlerContext) -> dict[str, Any]:
    """Re-parse a published document with the current parser/chunker versions."""
    document = _document(ctx)
    if document is None or document.status == "deleted":
        return {"pages": None, "skipped": True}
    if document.status != "uploaded":
        raise PermanentJobError("document_not_ready")
    if parsing.parser_for(document.mime_type) is None:
        raise PermanentJobError("unsupported_media_type")
    return _index(ctx, document, "reingest")


def _record_rejection(ctx: HandlerContext, document: Document, error: Exception) -> bool:
    rejection = getattr(error, "rejection", None)
    if rejection is None:
        return False
    knowledge.record_failed_version(
        ctx.db,
        document,
        code=rejection.code,
        parser=rejection.parser,
        parser_version=rejection.parser_version,
        now=ctx.clock(),
    )
    return True


def quarantine_document(ctx: HandlerContext, error: Exception) -> None:
    """Ingest failed for good: record the failed version (the active one is untouched) and
    either quarantine a suspicious upload or publish a valid-but-unindexable one."""
    document = _document(ctx)
    if document is None or document.status == "deleted":
        return
    recorded = _record_rejection(ctx, document, error)
    if document.status == "pending":
        rejection = getattr(error, "rejection", None)
        unindexable = recorded and rejection is not None and not rejection.suspicious
        document.status = "uploaded" if unindexable else "quarantined"
    ctx.db.flush()


def record_reingest_failure(ctx: HandlerContext, error: Exception) -> None:
    document = _document(ctx)
    if document is not None and document.status != "deleted":
        _record_rejection(ctx, document, error)
        ctx.db.flush()


def embed_document(ctx: HandlerContext) -> dict[str, Any]:
    """Retry only the embedding stage for the document's active version (KNOW-06)."""
    document = _document(ctx)
    if document is None or document.status == "deleted":
        return {"skipped": True}
    if not document.rights_attested:
        raise PermanentJobError("rights_attestation_required")
    if document.status != "uploaded" or document.active_version_id is None:
        raise PermanentJobError("document_not_ready")
    return indexing.embed_version(
        ctx.db,
        workspace_id=document.workspace_id,
        version_id=document.active_version_id,
        embedder=ctx.embedding_provider(),
        job_id=ctx.job.id,
        now=ctx.clock(),
    )


def delete_document_object(ctx: HandlerContext) -> dict[str, Any]:
    """KNOW-09: purge derived chunks/vectors (versions become ``withdrawn``), then the blob.
    Idempotent: a replay purges 0 rows and deletes an already-missing object without error,
    and a withdrawn version can never become active again (database transition guard)."""
    document = _document(ctx)
    if document is None:
        return {"deleted": False}
    if document.status != "deleted":
        raise PermanentJobError("document_not_deleted")
    purged = ctx.db.execute(
        text("SELECT edu.purge_document_chunks(:document_id)"), {"document_id": document.id}
    ).scalar_one()
    document.active_version_id = None
    ctx.db.flush()
    ctx.store.delete(document.object_key)  # idempotent in S3
    return {"deleted": True, "purgedChunks": int(purged or 0)}


def _permanent(code: str, source: Exception | None = None) -> PermanentJobError:
    error = PermanentJobError(code)
    error.metered = getattr(source, "metered", False)
    error.request_id = getattr(source, "request_id", None)
    return error


def generate_draft(ctx: HandlerContext) -> dict[str, Any]:
    """AUTHR-03: ``content.generate`` / ``questions.generate`` (provider outage -> failed)."""
    try:
        provider = ctx.llm_provider()
    except llm_service.ProviderNotConfigured:
        raise _permanent("provider_unavailable") from None
    try:
        return generation.run_generation(ctx, provider=provider)
    except generation.GenerationFailed as exc:
        raise _permanent(exc.code, exc) from None


def render_export(ctx: HandlerContext) -> dict[str, Any]:
    """EXPORT-01: render, upload under a server-chosen key and mark the export row."""
    try:
        return exports.run_export(ctx)
    except exports.ExportFailed as exc:
        raise _permanent(exc.code) from None


def grade_attempt(ctx: HandlerContext) -> dict[str, Any]:
    """ASMT-06: score a submitted attempt under the job's verified teacher context."""
    try:
        return scoring.grade_attempt_job(ctx.db, ctx.job, ctx.clock())
    except scoring.GradingRejected as exc:
        raise PermanentJobError(exc.code) from None


HANDLERS: dict[str, Handler] = {
    "document.ingest": Handler(ingest_document, quarantine_document),
    "document.reingest": Handler(reingest_document, record_reingest_failure),
    "document.delete": Handler(delete_document_object),
    "document.embed": Handler(embed_document),
    "content.generate": Handler(generate_draft, generation.mark_failed),
    "questions.generate": Handler(generate_draft, generation.mark_failed),
    "export.render": Handler(render_export, exports.mark_failed),
    "attempt.grade": Handler(grade_attempt),
}


def _enter_job_context(db: Session, job_id: UUID) -> bool:
    actor = db.execute(
        text("SELECT workspace_id, user_id, issuer, subject FROM edu.job_actor(:id)"),
        {"id": job_id},
    ).first()
    if actor is None:
        return False
    set_actor_context(
        db,
        issuer=actor.issuer,
        subject=actor.subject,
        user_id=actor.user_id,
        workspace_id=actor.workspace_id,
    )
    return True


def _retry_countdown(attempt: int) -> int:
    return min(300, 10 * 2 ** max(0, attempt - 1))


def execute_job(
    job_id: UUID,
    *,
    sessions: sessionmaker[Session],
    store: ObjectStore,
    send: Callable[..., None] = job_service.send_job,
    clock: Callable[[], datetime] = job_service.utcnow,
    max_bytes: int | None = None,
    embedder: embeddings.EmbeddingProvider | None = None,
    llm_provider: llm_service.LLMProvider | None = None,
) -> str:
    with sessions() as db:
        with db.begin():
            if not _enter_job_context(db, job_id):
                logger.warning("job_actor_unavailable")
                return "skipped"
            attempt = job_service.claim_job(db, job_id, clock())
        if attempt is None:
            return "not_claimed"

        failure: Exception | None = None
        kind = ""
        try:
            with db.begin():
                _enter_job_context(db, job_id)
                job = job_service.running_attempt(db, job_id, attempt)
                if job is None:
                    return "stale"
                kind = job.kind
                if job.cancel_requested:
                    job_service.cancel_running(db, job_id, attempt, clock())
                    return "cancelled"
                handler = HANDLERS.get(job.kind)
                if handler is None:
                    raise PermanentJobError("unknown_job_kind")
                result = handler.run(
                    HandlerContext(db, job, store, clock(), max_bytes, embedder, llm_provider)
                )
                job_service.complete_job(db, job_id, attempt, result, clock())
            return "succeeded"
        except Exception as exc:
            failure = exc

        permanent = isinstance(failure, PermanentJobError)
        code = failure.code if permanent else "transient_error"
        logger.warning("job_failed", extra={"error_type": type(failure).__name__})
        with db.begin():
            _enter_job_context(db, job_id)
            job = job_service.running_attempt(db, job_id, attempt)
            if job is None:
                return "stale"
            outcome = job_service.fail_job(
                db, job_id, attempt, code, retryable=not permanent, now=clock()
            )
            handler = HANDLERS.get(job.kind)
            if outcome == "failed" and handler and handler.on_permanent_failure:
                handler.on_permanent_failure(
                    HandlerContext(db, job, store, clock(), max_bytes, embedder, llm_provider),
                    failure,
                )
        if outcome == "queued":
            try:
                send(job_id, kind, countdown=_retry_countdown(attempt))
            except Exception as exc:  # the sweeper re-dispatches stale queued jobs
                logger.warning("job_dispatch_failed", extra={"error_type": type(exc).__name__})
        return outcome or "stale"


def sweep_jobs(
    *,
    sessions: sessionmaker[Session],
    send: Callable[..., None] = job_service.send_job,
    clock: Callable[[], datetime] = job_service.utcnow,
    limit: int = 100,
) -> list[job_service.SweepOutcome]:
    now = clock()
    with sessions() as db:
        with db.begin():
            ids = list(
                db.execute(
                    text("SELECT edu.overdue_job_ids(:now, :queued_before, :limit)"),
                    {
                        "now": now,
                        "queued_before": now - job_service.DISPATCH_TIMEOUT,
                        "limit": limit,
                    },
                ).scalars()
            )
        outcomes: list[job_service.SweepOutcome] = []
        for job_id in ids:
            with db.begin():
                if not _enter_job_context(db, job_id):
                    continue
                found = job_service.sweep_overdue(db, now, job_ids=[job_id])
                kinds = {
                    o.job_id: db.get(BackgroundJob, o.job_id).kind
                    for o in found
                    if o.action in {"requeued", "redispatch"}
                }
            for outcome in found:
                if outcome.job_id in kinds:
                    try:
                        send(outcome.job_id, kinds[outcome.job_id])
                    except Exception as exc:
                        logger.warning(
                            "job_dispatch_failed", extra={"error_type": type(exc).__name__}
                        )
            outcomes.extend(found)
    return outcomes


def sweep_assessments(
    *,
    sessions: sessionmaker[Session],
    send: Callable[..., None] = job_service.send_job,
    clock: Callable[[], datetime] = job_service.utcnow,
) -> dict[str, int]:
    """ASMT-05/07: finalize attempts past ``deadline_at`` + grace (reason ``deadline``), enqueue
    their grading, then apply due ``after_close`` releases.

    Both steps are cross-tenant SECURITY DEFINER functions returning ids only. Expiry and the
    release run in separate transactions so a release never waits on attempt locks. A grading
    job whose dispatch fails stays queued and is re-dispatched by ``sweep_jobs``.
    """
    now = clock()
    with sessions() as db:
        with db.begin():
            expired = attempts.expire_due(db, now)
        with db.begin():
            released = releases.apply_due_releases(db, now)
    for item in expired:
        if item.job_id is None:
            continue
        try:
            send(item.job_id, "attempt.grade")
        except Exception as exc:
            logger.warning("job_dispatch_failed", extra={"error_type": type(exc).__name__})
    return {"expired": len(expired), **releases.release_summary(released)}


_store: ObjectStore | None = None
_embedder: embeddings.EmbeddingProvider | None = None
_llm: llm_service.LLMProvider | None = None


def default_llm() -> llm_service.LLMProvider:
    global _llm
    if _llm is None:
        _llm = llm_service.get_llm_provider(get_settings())
    return _llm


def default_embedder() -> embeddings.EmbeddingProvider:
    global _embedder
    if _embedder is None:
        _embedder = embeddings.get_embedder(get_settings())
    return _embedder


def default_store() -> ObjectStore:
    global _store
    if _store is None:
        _store = ObjectStore(get_settings())
    return _store


@celery_app.task(
    name="app.tasks.jobs.run",
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def run(job_id: str) -> str:
    return execute_job(UUID(job_id), sessions=get_sync_sessionmaker(), store=default_store())


@celery_app.task(name="app.tasks.jobs.sweep", ignore_result=True)
def sweep() -> int:
    started = datetime.now(UTC)
    try:
        sweep_assessments(sessions=get_sync_sessionmaker())
    except Exception as exc:  # never block the job sweep below
        logger.warning("assessment_sweep_failed", extra={"error_type": type(exc).__name__})
    outcomes = sweep_jobs(sessions=get_sync_sessionmaker())
    logger.info(
        "jobs_swept",
        extra={"duration_ms": round((datetime.now(UTC) - started).total_seconds() * 1000, 2)},
    )
    return len(outcomes)
