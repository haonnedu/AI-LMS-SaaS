"""Private document upload/download (STORE-01 lean).

Uploads are a raw request body (no multipart): ``Content-Type`` is the file MIME type,
``X-File-Name`` the percent-encoded UTF-8 name, ``X-Rights-Attested: true`` is required and
``Idempotency-Key`` optional. Object keys are derived on the server; signed URLs and keys are
never logged.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.api.identity import ApiError, Claims, Database, ErrorDTO
from app.api.jobs import TEACHING_ROLES, JobDTO, dispatcher, job_dto, keyset, next_cursor
from app.api.workspace_access import workspace_transaction
from app.core.audit import audit
from app.models.documents import Document
from app.services import jobs as job_service
from app.services import usage
from app.services.storage import (
    ObjectStore,
    check_content,
    check_declared_size,
    normalize_mime,
    object_key,
    read_upload,
    validate_file_name,
)


class DocumentDTO(BaseModel):
    id: UUID
    workspaceId: UUID
    fileName: str
    mimeType: str
    sizeBytes: int
    sha256: str
    status: Literal["pending", "uploaded", "quarantined", "deleted"]
    rightsAttested: bool
    createdAt: datetime
    deletedAt: datetime | None


class DocumentJobDTO(BaseModel):
    document: DocumentDTO
    job: JobDTO


class DocumentListDTO(BaseModel):
    items: list[DocumentDTO]
    nextCursor: str | None


class DownloadDTO(BaseModel):
    url: str
    expiresAt: datetime


router = APIRouter(
    prefix="/v1",
    tags=["documents"],
    responses={
        status: {"model": ErrorDTO} for status in (401, 403, 404, 409, 413, 415, 422, 429, 503)
    },
)


def document_dto(document: Document) -> DocumentDTO:
    return DocumentDTO(
        id=document.id,
        workspaceId=document.workspace_id,
        fileName=document.file_name,
        mimeType=document.mime_type,
        sizeBytes=document.size_bytes,
        sha256=bytes(document.sha256).hex(),
        status=document.status,
        rightsAttested=document.rights_attested,
        createdAt=document.created_at,
        deletedAt=document.deleted_at,
    )


def object_store(request: Request) -> ObjectStore:
    store = getattr(request.app.state, "object_store", None)
    if store is None:
        store = ObjectStore(request.app.state.settings)
        request.app.state.object_store = store
    return store


def request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def load_document(
    db, workspace_id: UUID, document_id: UUID, *, lock: bool = False, include_deleted=False
) -> Document:
    query = select(Document).where(
        Document.id == document_id, Document.workspace_id == workspace_id
    )
    if lock:
        query = query.with_for_update()
    document = await db.scalar(query)
    if document is None or (document.status == "deleted" and not include_deleted):
        raise ApiError(404, "document_not_found", "Không tìm thấy tài liệu.")
    return document


async def _discard(store: ObjectStore, key: str) -> None:
    try:
        await store.adelete(key)
    except Exception:  # orphan objects are reconciled later; never mask the original error
        pass


@router.post("/workspaces/{workspace_id}/documents", status_code=202, response_model=DocumentJobDTO)
async def upload_document(
    workspace_id: UUID,
    request: Request,
    db: Database,
    claims: Claims,
    x_file_name: Annotated[str | None, Header()] = None,
    x_rights_attested: Annotated[str | None, Header()] = None,
    content_type: Annotated[str | None, Header()] = None,
    content_length: Annotated[int | None, Header()] = None,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    max_bytes = request.app.state.settings.upload_max_bytes
    if (x_rights_attested or "").strip().lower() != "true":
        raise ApiError(
            422,
            "rights_attestation_required",
            "Bạn cần xác nhận có quyền sử dụng tài liệu trước khi tải lên.",
        )
    mime = normalize_mime(content_type)
    file_name = validate_file_name(x_file_name, mime)
    check_declared_size(content_length, max_bytes)
    key = job_service.client_idempotency_key(idempotency_key)

    # Authorize before accepting any bytes; no transaction is held while streaming.
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES):
        pass
    upload = await read_upload(request.stream(), max_bytes)
    store = object_store(request)
    document_id = uuid4()
    storage_key = object_key(workspace_id, document_id)
    try:
        check_content(mime, upload.head)
        digest = job_service.request_hash(
            "document.upload",
            {
                "fileName": file_name,
                "mimeType": mime,
                "sizeBytes": upload.size,
                "sha256": upload.sha256.hex(),
            },
        )
        await store.aput(
            storage_key, upload.file, mime=mime, size=upload.size, sha256=upload.sha256
        )
    finally:
        upload.close()

    created = False
    try:
        async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES) as scope:
            job, created = await job_service.enqueue_job(
                db,
                scope,
                "document.ingest",
                {"documentId": str(document_id)},
                key,
                digest=digest,
            )
            if created:
                await usage.reserve(db, scope, usage.units_for_bytes(upload.size), job_id=job.id)
                now = datetime.now(UTC)
                document = Document(
                    id=document_id,
                    workspace_id=workspace_id,
                    owner_user_id=scope.user.id,
                    file_name=file_name,
                    mime_type=mime,
                    size_bytes=upload.size,
                    sha256=upload.sha256,
                    object_key=storage_key,
                    status="pending",
                    rights_attested=True,
                    created_at=now,
                )
                db.add(document)
                await db.flush()
            else:
                document = await load_document(
                    db, workspace_id, UUID(job.input["documentId"]), include_deleted=True
                )
    except Exception:
        await _discard(store, storage_key)
        raise
    if not created:
        await _discard(store, storage_key)  # idempotent replay: keep the original object only
        return DocumentJobDTO(document=document_dto(document), job=job_dto(job))
    audit(
        "document.upload",
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        document_id=document.id,
        job_id=job.id,
        mime_type=mime,
        size_bytes=upload.size,
    )
    await dispatcher(request)(job)
    return DocumentJobDTO(document=document_dto(document), job=job_dto(job))


@router.get("/workspaces/{workspace_id}/documents", response_model=DocumentListDTO)
async def list_documents(
    workspace_id: UUID,
    db: Database,
    claims: Claims,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES):
        rows = list(
            (
                await db.scalars(
                    select(Document)
                    .where(
                        Document.workspace_id == workspace_id,
                        Document.status != "deleted",
                        *keyset(Document, cursor),
                    )
                    .order_by(Document.created_at.desc(), Document.id.desc())
                    .limit(limit + 1)
                )
            ).all()
        )
        return DocumentListDTO(
            items=[document_dto(row) for row in rows[:limit]],
            nextCursor=next_cursor(rows, limit),
        )


@router.get("/workspaces/{workspace_id}/documents/{document_id}", response_model=DocumentDTO)
async def get_document(workspace_id: UUID, document_id: UUID, db: Database, claims: Claims):
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES):
        return document_dto(await load_document(db, workspace_id, document_id))


@router.get(
    "/workspaces/{workspace_id}/documents/{document_id}/download", response_model=DownloadDTO
)
async def download_document(
    workspace_id: UUID, document_id: UUID, request: Request, db: Database, claims: Claims
):
    # Fresh permission check on every call; revocation stops new URLs immediately.
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES):
        document = await load_document(db, workspace_id, document_id)
    if document.status != "uploaded":
        raise ApiError(409, "document_not_ready", "Tài liệu chưa sẵn sàng để tải xuống.")
    url, expires_at = object_store(request).presign_get(
        document.object_key, file_name=document.file_name, mime=document.mime_type
    )
    return DownloadDTO(url=url, expiresAt=expires_at)


@router.delete(
    "/workspaces/{workspace_id}/documents/{document_id}",
    status_code=202,
    response_model=DocumentJobDTO,
)
async def delete_document(
    workspace_id: UUID, document_id: UUID, request: Request, db: Database, claims: Claims
):
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES) as scope:
        document = await load_document(
            db, workspace_id, document_id, lock=True, include_deleted=True
        )
        newly_deleted = document.status != "deleted"
        if newly_deleted:
            document.status = "deleted"
            document.deleted_at = datetime.now(UTC)
            await db.flush()
        payload = {"documentId": str(document.id)}
        job, created = await job_service.enqueue_job(
            db,
            scope,
            "document.delete",
            payload,
            job_service.SYSTEM_KEY_PREFIX + "document.delete:" + str(document.id),
        )
    if newly_deleted:
        audit(
            "document.delete",
            request_id=request_id(request),
            user_id=scope.user.id,
            workspace_id=workspace_id,
            document_id=document.id,
            job_id=job.id,
        )
    if created:
        await dispatcher(request)(job)
    return DocumentJobDTO(document=document_dto(document), job=job_dto(job))
