"""Workspace job status, cancel and retry (JOB-05 lean). Every call re-authorizes."""

import base64
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, or_, select

from app.api.identity import ApiError, Claims, Database, ErrorDTO
from app.api.workspace_access import workspace_transaction
from app.core.audit import audit
from app.models.jobs import BackgroundJob
from app.services import jobs as job_service

TEACHING_ROLES = frozenset({"owner", "admin", "teacher"})
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class JobDTO(BaseModel):
    id: UUID
    workspaceId: UUID
    kind: str
    status: JobStatus
    attempt: int
    maxAttempts: int
    cancelRequested: bool
    errorCode: str | None
    result: dict[str, Any] | None
    createdAt: datetime
    startedAt: datetime | None
    finishedAt: datetime | None
    updatedAt: datetime


class JobListDTO(BaseModel):
    items: list[JobDTO]
    nextCursor: str | None


router = APIRouter(
    prefix="/v1",
    tags=["jobs"],
    responses={status: {"model": ErrorDTO} for status in (401, 403, 404, 409, 422, 503)},
)


def job_dto(job: BackgroundJob) -> JobDTO:
    return JobDTO(
        id=job.id,
        workspaceId=job.workspace_id,
        kind=job.kind,
        status=job.status,
        attempt=job.attempt,
        maxAttempts=job.max_attempts,
        cancelRequested=job.cancel_requested,
        errorCode=job.error_code,
        result=job.result,
        createdAt=job.created_at,
        startedAt=job.started_at,
        finishedAt=job.finished_at,
        updatedAt=job.updated_at,
    )


def encode_cursor(created_at: datetime, row_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created, row_id = base64.urlsafe_b64decode(padded).decode().split("|", 1)
        parsed = datetime.fromisoformat(created)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed, UUID(row_id)
    except (ValueError, UnicodeDecodeError):
        raise ApiError(422, "invalid_cursor", "Con trỏ phân trang không hợp lệ.") from None


def keyset(model, cursor: str | None):
    """Newest first; ``(created_at, id)`` keyset so pages are stable under inserts."""
    if not cursor:
        return []
    created, row_id = decode_cursor(cursor)
    return [or_(model.created_at < created, and_(model.created_at == created, model.id < row_id))]


def next_cursor(rows: list, limit: int) -> str | None:
    if len(rows) <= limit:
        return None
    last = rows[limit - 1]
    return encode_cursor(last.created_at, last.id)


async def load_job(db, workspace_id: UUID, job_id: UUID, *, lock: bool = False) -> BackgroundJob:
    query = select(BackgroundJob).where(
        BackgroundJob.id == job_id, BackgroundJob.workspace_id == workspace_id
    )
    if lock:
        query = query.with_for_update()
    job = await db.scalar(query)
    if job is None:
        raise ApiError(404, "job_not_found", "Không tìm thấy tác vụ.")
    return job


@router.get("/workspaces/{workspace_id}/jobs", response_model=JobListDTO)
async def list_jobs(
    workspace_id: UUID,
    db: Database,
    claims: Claims,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status: JobStatus | None = None,
):
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES):
        query = (
            select(BackgroundJob)
            .where(BackgroundJob.workspace_id == workspace_id, *keyset(BackgroundJob, cursor))
            .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
            .limit(limit + 1)
        )
        if status:
            query = query.where(BackgroundJob.status == status)
        rows = list((await db.scalars(query)).all())
        return JobListDTO(
            items=[job_dto(job) for job in rows[:limit]], nextCursor=next_cursor(rows, limit)
        )


@router.get("/workspaces/{workspace_id}/jobs/{job_id}", response_model=JobDTO)
async def get_job(workspace_id: UUID, job_id: UUID, db: Database, claims: Claims):
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES):
        return job_dto(await load_job(db, workspace_id, job_id))


@router.post("/workspaces/{workspace_id}/jobs/{job_id}/cancel", response_model=JobDTO)
async def cancel_job(
    workspace_id: UUID, job_id: UUID, request: Request, db: Database, claims: Claims
):
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES) as scope:
        job = await load_job(db, workspace_id, job_id, lock=True)
        changed = job_service.request_cancel(job)
        await db.flush()
    if changed:
        audit(
            "job.cancel",
            request_id=getattr(request.state, "request_id", None),
            user_id=scope.user.id,
            workspace_id=workspace_id,
            job_id=job.id,
            kind=job.kind,
            status=job.status,
        )
    return job_dto(job)


@router.post("/workspaces/{workspace_id}/jobs/{job_id}/retry", response_model=JobDTO)
async def retry_job(
    workspace_id: UUID, job_id: UUID, request: Request, db: Database, claims: Claims
):
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES) as scope:
        job = await load_job(db, workspace_id, job_id, lock=True)
        changed = job_service.request_retry(job)
        await db.flush()
    if changed:
        audit(
            "job.retry",
            request_id=getattr(request.state, "request_id", None),
            user_id=scope.user.id,
            workspace_id=workspace_id,
            job_id=job.id,
            kind=job.kind,
        )
        await dispatcher(request)(job)
    return job_dto(job)


def dispatcher(request: Request):
    """Tests and alternative transports may set ``app.state.job_dispatcher``."""
    return getattr(request.app.state, "job_dispatcher", None) or job_service.dispatch_job
