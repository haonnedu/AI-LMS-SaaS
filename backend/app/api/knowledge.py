"""Curriculum metadata, document versions/chunks, re-ingest and curriculum tags (KNOW-01..05).

Curriculum listing is platform metadata readable by any onboarded user. Everything under a
workspace re-authorizes through ``workspace_transaction`` with teaching roles; chunk text is
returned only to teachers of the owning workspace (it is their own private document). No
endpoint here can publish a document beyond its workspace: ``rights_scope`` is private-only.
"""

import base64
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.documents import DocumentJobDTO, document_dto, load_document, request_id
from app.api.identity import ApiError, Claims, Database, ErrorDTO, current_user
from app.api.jobs import TEACHING_ROLES, dispatcher, job_dto
from app.api.workspace_access import workspace_transaction
from app.core.audit import audit
from app.models.knowledge import (
    CurriculumSubject,
    CurriculumUnit,
    DocumentChunk,
    DocumentCurriculumTag,
    DocumentVersion,
)
from app.services import chunking, knowledge
from app.services import jobs as job_service

MAX_TAGS = 50
VersionStatus = Literal["processing", "active", "failed", "superseded"]

# Safe, user-facing explanations for version error codes (codes stay stable for clients).
ERROR_MESSAGES = {
    "pdf_parser_unavailable": "Hệ thống chưa hỗ trợ đọc nội dung PDF; tệp vẫn được lưu an toàn.",
    "no_text_layer": "PDF không có lớp văn bản (bản scan); chưa hỗ trợ nhận dạng chữ (OCR).",
    "encrypted_document": "Tệp được đặt mật khẩu hoặc mã hóa nên không thể đọc nội dung.",
    "unsupported_media_type": "Loại tệp này chưa được hỗ trợ để trích xuất nội dung.",
    "empty_document": "Không tìm thấy nội dung văn bản trong tệp.",
    "document_too_long": "Tài liệu quá dài để xử lý.",
    "too_many_pages": "Tài liệu có quá nhiều trang để xử lý.",
    "document_too_large": "Tệp vượt quá giới hạn kích thước xử lý.",
    "malformed_document": "Tệp bị hỏng hoặc không đúng định dạng.",
    "archive_too_large": "Tệp có cấu trúc nén bất thường nên đã bị từ chối.",
    "invalid_text_encoding": "Không đọc được bảng mã của tệp văn bản.",
    "parse_timeout": "Xử lý tệp quá thời gian cho phép.",
    "parse_resource_limit": "Xử lý tệp vượt quá giới hạn tài nguyên.",
    "rights_attestation_required": "Tài liệu chưa có xác nhận quyền sử dụng.",
}


class CurriculumSubjectDTO(BaseModel):
    id: UUID
    code: str
    nameVi: str


class CurriculumSubjectListDTO(BaseModel):
    items: list[CurriculumSubjectDTO]


class CurriculumUnitDTO(BaseModel):
    id: UUID
    subjectId: UUID
    grade: int
    programYear: str
    unitCode: str
    titleVi: str
    parentId: UUID | None
    sortOrder: int
    sourceProvenance: str
    version: int


class CurriculumUnitListDTO(BaseModel):
    items: list[CurriculumUnitDTO]


class DocumentVersionDTO(BaseModel):
    id: UUID
    documentId: UUID
    versionNo: int
    status: VersionStatus
    parser: str
    parserVersion: str
    chunkerVersion: str
    pageCount: int | None
    charCount: int
    chunkCount: int
    textSha256: str | None
    errorCode: str | None
    errorMessage: str | None
    createdAt: datetime
    activatedAt: datetime | None


class DocumentVersionListDTO(BaseModel):
    items: list[DocumentVersionDTO]
    activeVersionId: UUID | None


class DocumentChunkDTO(BaseModel):
    id: UUID
    chunkIndex: int
    pageNo: int | None
    sectionPath: str | None
    charStart: int
    charEnd: int
    tokenEstimate: int
    textSha256: str
    text: str


class DocumentChunkListDTO(BaseModel):
    items: list[DocumentChunkDTO]
    nextCursor: str | None


class CurriculumTagsRequest(BaseModel):
    unitIds: list[UUID] = Field(max_length=MAX_TAGS)


router = APIRouter(
    prefix="/v1",
    tags=["knowledge"],
    responses={status: {"model": ErrorDTO} for status in (401, 403, 404, 409, 422, 503)},
)


def unit_dto(unit: CurriculumUnit) -> CurriculumUnitDTO:
    return CurriculumUnitDTO(
        id=unit.id,
        subjectId=unit.subject_id,
        grade=unit.grade,
        programYear=unit.program_year,
        unitCode=unit.unit_code,
        titleVi=unit.title_vi,
        parentId=unit.parent_id,
        sortOrder=unit.sort_order,
        sourceProvenance=unit.source_provenance,
        version=unit.version,
    )


def version_dto(version: DocumentVersion) -> DocumentVersionDTO:
    return DocumentVersionDTO(
        id=version.id,
        documentId=version.document_id,
        versionNo=version.version_no,
        status=version.status,
        parser=version.parser,
        parserVersion=version.parser_version,
        chunkerVersion=version.chunker_version,
        pageCount=version.page_count,
        charCount=version.char_count,
        chunkCount=version.chunk_count,
        textSha256=bytes(version.text_sha256).hex() if version.text_sha256 else None,
        errorCode=version.error_code,
        errorMessage=(
            ERROR_MESSAGES.get(version.error_code, "Không thể xử lý tài liệu.")
            if version.error_code
            else None
        ),
        createdAt=version.created_at,
        activatedAt=version.activated_at,
    )


def chunk_dto(chunk: DocumentChunk) -> DocumentChunkDTO:
    return DocumentChunkDTO(
        id=chunk.id,
        chunkIndex=chunk.chunk_index,
        pageNo=chunk.page_no,
        sectionPath=chunk.section_path,
        charStart=chunk.char_start,
        charEnd=chunk.char_end,
        tokenEstimate=chunk.token_estimate,
        textSha256=bytes(chunk.text_sha256).hex(),
        text=chunk.text,
    )


def encode_chunk_cursor(chunk_index: int) -> str:
    return base64.urlsafe_b64encode(f"chunk:{chunk_index}".encode()).decode().rstrip("=")


def decode_chunk_cursor(cursor: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        prefix, value = raw.split(":", 1)
        index = int(value)
        if prefix != "chunk" or index < 0:
            raise ValueError
        return index
    except (ValueError, UnicodeDecodeError):
        raise ApiError(422, "invalid_cursor", "Con trỏ phân trang không hợp lệ.") from None


async def authenticated(db, claims) -> None:
    """Platform metadata: any onboarded, active user (no workspace context needed)."""
    await current_user(db, claims)


# ------------------------------------------------------------------ curriculum (platform-wide)


@router.get("/curriculum/subjects", response_model=CurriculumSubjectListDTO)
async def list_subjects(db: Database, claims: Claims):
    async with db.begin():
        await authenticated(db, claims)
        rows = (await db.scalars(select(CurriculumSubject).order_by(CurriculumSubject.code))).all()
    return CurriculumSubjectListDTO(
        items=[CurriculumSubjectDTO(id=s.id, code=s.code, nameVi=s.name_vi) for s in rows]
    )


@router.get("/curriculum/units", response_model=CurriculumUnitListDTO)
async def list_units(
    db: Database,
    claims: Claims,
    subject: Annotated[str | None, Query(pattern=r"^[a-z0-9-]{1,32}$")] = None,
    grade: Annotated[int | None, Query(ge=1, le=12)] = None,
    program_year: Annotated[str | None, Query(alias="programYear", pattern=r"^[0-9]{4}$")] = None,
):
    query = select(CurriculumUnit)
    if subject is not None:
        query = query.join(CurriculumSubject, CurriculumSubject.id == CurriculumUnit.subject_id)
        query = query.where(CurriculumSubject.code == subject)
    if grade is not None:
        query = query.where(CurriculumUnit.grade == grade)
    if program_year is not None:
        query = query.where(CurriculumUnit.program_year == program_year)
    query = query.order_by(
        CurriculumUnit.grade, CurriculumUnit.sort_order, CurriculumUnit.unit_code
    ).limit(1000)
    async with db.begin():
        await authenticated(db, claims)
        rows = (await db.scalars(query)).all()
    return CurriculumUnitListDTO(items=[unit_dto(unit) for unit in rows])


# ------------------------------------------------------------------ document versions/chunks


@router.get(
    "/workspaces/{workspace_id}/documents/{document_id}/versions",
    response_model=DocumentVersionListDTO,
)
async def list_versions(workspace_id: UUID, document_id: UUID, db: Database, claims: Claims):
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES):
        document = await load_document(db, workspace_id, document_id)
        rows = (
            await db.scalars(
                select(DocumentVersion)
                .where(
                    DocumentVersion.workspace_id == workspace_id,
                    DocumentVersion.document_id == document.id,
                )
                .order_by(DocumentVersion.version_no.desc())
                .limit(200)
            )
        ).all()
        return DocumentVersionListDTO(
            items=[version_dto(row) for row in rows], activeVersionId=document.active_version_id
        )


@router.get(
    "/workspaces/{workspace_id}/documents/{document_id}/versions/{version_id}/chunks",
    response_model=DocumentChunkListDTO,
)
async def list_chunks(
    workspace_id: UUID,
    document_id: UUID,
    version_id: UUID,
    db: Database,
    claims: Claims,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    after = decode_chunk_cursor(cursor) if cursor else None
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES):
        document = await load_document(db, workspace_id, document_id)
        version = await db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id,
                DocumentVersion.workspace_id == workspace_id,
                DocumentVersion.document_id == document.id,
            )
        )
        if version is None:
            raise ApiError(404, "version_not_found", "Không tìm thấy phiên bản tài liệu.")
        query = select(DocumentChunk).where(
            DocumentChunk.workspace_id == workspace_id,
            DocumentChunk.document_version_id == version.id,
        )
        if after is not None:
            query = query.where(DocumentChunk.chunk_index > after)
        rows = list(
            (await db.scalars(query.order_by(DocumentChunk.chunk_index).limit(limit + 1))).all()
        )
        page = rows[:limit]
        return DocumentChunkListDTO(
            items=[chunk_dto(row) for row in page],
            nextCursor=encode_chunk_cursor(page[-1].chunk_index) if len(rows) > limit else None,
        )


@router.post(
    "/workspaces/{workspace_id}/documents/{document_id}/reingest",
    status_code=202,
    response_model=DocumentJobDTO,
)
async def reingest_document(
    workspace_id: UUID,
    document_id: UUID,
    request: Request,
    db: Database,
    claims: Claims,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES) as scope:
        document = await load_document(db, workspace_id, document_id, lock=True)
        if not document.rights_attested:
            raise ApiError(
                409,
                "rights_attestation_required",
                "Tài liệu chưa có xác nhận quyền sử dụng nên không thể xử lý lại.",
            )
        if document.status != "uploaded":
            raise ApiError(409, "document_not_ready", "Tài liệu chưa sẵn sàng để xử lý lại.")
        parser, parser_version = knowledge.parser_identity(document.mime_type)
        payload = {"documentId": str(document.id)}
        # Without a client key, one re-ingest per document and pipeline version: repeated
        # clicks return the same job; a newer parser/chunker gets a fresh job.
        key = (
            job_service.client_idempotency_key(idempotency_key)
            if idempotency_key is not None
            else (
                f"{job_service.SYSTEM_KEY_PREFIX}document.reingest:{document.id}:"
                f"{parser}-{parser_version}:{chunking.CHUNKER_VERSION}"
            )
        )
        job, created = await job_service.enqueue_job(db, scope, "document.reingest", payload, key)
    if created:
        audit(
            "document.reingest",
            request_id=request_id(request),
            user_id=scope.user.id,
            workspace_id=workspace_id,
            document_id=document.id,
            job_id=job.id,
        )
        await dispatcher(request)(job)
    return DocumentJobDTO(document=document_dto(document), job=job_dto(job))


# ------------------------------------------------------------------ curriculum tags


async def _tagged_units(db, workspace_id: UUID, document_id: UUID) -> list[CurriculumUnit]:
    rows = await db.scalars(
        select(CurriculumUnit)
        .join(
            DocumentCurriculumTag,
            DocumentCurriculumTag.curriculum_unit_id == CurriculumUnit.id,
        )
        .where(
            DocumentCurriculumTag.workspace_id == workspace_id,
            DocumentCurriculumTag.document_id == document_id,
        )
        .order_by(CurriculumUnit.grade, CurriculumUnit.sort_order, CurriculumUnit.unit_code)
    )
    return list(rows.all())


@router.get(
    "/workspaces/{workspace_id}/documents/{document_id}/curriculum-tags",
    response_model=CurriculumUnitListDTO,
)
async def get_curriculum_tags(workspace_id: UUID, document_id: UUID, db: Database, claims: Claims):
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES):
        document = await load_document(db, workspace_id, document_id)
        units = await _tagged_units(db, workspace_id, document.id)
        return CurriculumUnitListDTO(items=[unit_dto(unit) for unit in units])


@router.put(
    "/workspaces/{workspace_id}/documents/{document_id}/curriculum-tags",
    response_model=CurriculumUnitListDTO,
)
async def put_curriculum_tags(
    workspace_id: UUID,
    document_id: UUID,
    body: CurriculumTagsRequest,
    request: Request,
    db: Database,
    claims: Claims,
):
    unit_ids = list(dict.fromkeys(body.unitIds))  # dedupe, keep order
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES) as scope:
        document = await load_document(db, workspace_id, document_id, lock=True)
        if unit_ids:
            found = set(
                (
                    await db.scalars(
                        select(CurriculumUnit.id).where(CurriculumUnit.id.in_(unit_ids))
                    )
                ).all()
            )
            if found != set(unit_ids):
                raise ApiError(
                    422, "curriculum_unit_not_found", "Có đơn vị chương trình không tồn tại."
                )
        await db.execute(
            delete(DocumentCurriculumTag).where(
                DocumentCurriculumTag.workspace_id == workspace_id,
                DocumentCurriculumTag.document_id == document.id,
            )
        )
        for unit_id in unit_ids:
            db.add(
                DocumentCurriculumTag(
                    workspace_id=workspace_id, document_id=document.id, curriculum_unit_id=unit_id
                )
            )
        await db.flush()
        units = await _tagged_units(db, workspace_id, document.id)
    audit(
        "document.curriculum_tags",
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        document_id=document.id,
        tag_count=len(unit_ids),
    )
    return CurriculumUnitListDTO(items=[unit_dto(unit) for unit in units])
