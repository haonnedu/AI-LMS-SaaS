"""Authorized retrieval, citation preview and embedding retries (KNOW-06..09).

Every endpoint re-authorizes through ``workspace_transaction`` with teaching roles; retrieval
SQL runs inside it (RLS + explicit workspace/lifecycle predicates). Queries and chunk text are
never logged or audited; audits carry counts only. Query embeddings are metered (1 unit per
query, ``embedding_ktok``) against the workspace's monthly cap before the provider is called;
if the provider is unavailable the request degrades to lexical-only retrieval, never to a
wider scope.
"""

import asyncio
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.documents import DocumentJobDTO, document_dto, load_document, request_id
from app.api.identity import ApiError, Claims, Database, ErrorDTO
from app.api.jobs import TEACHING_ROLES, dispatcher, job_dto
from app.api.workspace_access import workspace_transaction
from app.core.audit import audit
from app.models.knowledge import DocumentVersion, EmbeddingRun
from app.services import citations, embeddings, indexing, retrieval, usage
from app.services import jobs as job_service

QUERY_UNITS = 1


class RetrievalQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=retrieval.MAX_QUERY_CHARS)
    documentIds: list[UUID] | None = Field(default=None, max_length=retrieval.MAX_DOCUMENT_FILTER)
    k: int = Field(default=retrieval.DEFAULT_K, ge=1, le=retrieval.MAX_K)


class RetrievedItemDTO(BaseModel):
    chunkId: UUID
    documentId: UUID
    versionId: UUID
    pageNo: int | None
    sectionPath: str | None
    snippet: str
    score: float
    citation: str
    sources: list[str]


class RetrievalResultDTO(BaseModel):
    items: list[RetrievedItemDTO]
    model: str
    mode: Literal["hybrid", "lexical"]
    abstained: bool


class CitationPreviewDTO(BaseModel):
    chunkId: UUID
    documentId: UUID
    versionId: UUID
    versionNo: int
    versionStatus: str
    fileName: str
    pageNo: int | None
    sectionPath: str | None
    charStart: int
    charEnd: int
    snippet: str
    text: str
    textSha256: str
    activatedAt: datetime | None


class EmbeddingRunDTO(BaseModel):
    id: UUID
    versionId: UUID
    jobId: UUID | None
    model: str
    version: str
    status: Literal["pending", "succeeded", "failed"]
    chunkCount: int
    units: int
    errorCode: str | None
    createdAt: datetime
    finishedAt: datetime | None


class EmbeddingRunListDTO(BaseModel):
    items: list[EmbeddingRunDTO]
    currentModel: str
    currentVersion: str


router = APIRouter(
    prefix="/v1",
    tags=["retrieval"],
    responses={status: {"model": ErrorDTO} for status in (401, 403, 404, 409, 422, 429, 503)},
)


def embedder(request: Request) -> embeddings.EmbeddingProvider:
    """Tests may set ``app.state.embedder``; otherwise built once from settings."""
    current = getattr(request.app.state, "embedder", None)
    if current is None:
        current = embeddings.get_embedder(request.app.state.settings)
        request.app.state.embedder = current
    return current


def max_distance(request: Request) -> float:
    settings = getattr(request.app.state, "settings", None)
    return getattr(settings, "retrieval_max_cosine_distance", retrieval.DEFAULT_MAX_DISTANCE)


def item_dto(chunk: retrieval.RetrievedChunk, citation: citations.Citation) -> RetrievedItemDTO:
    return RetrievedItemDTO(
        chunkId=chunk.chunk_id,
        documentId=chunk.document_id,
        versionId=chunk.version_id,
        pageNo=chunk.page_no,
        sectionPath=chunk.section_path,
        snippet=citation.snippet,
        score=chunk.score,
        citation=citation.label,
        sources=list(chunk.sources),
    )


def run_dto(run: EmbeddingRun) -> EmbeddingRunDTO:
    return EmbeddingRunDTO(
        id=run.id,
        versionId=run.document_version_id,
        jobId=run.job_id,
        model=run.model,
        version=run.version,
        status=run.status,
        chunkCount=run.chunk_count,
        units=run.units,
        errorCode=run.error_code,
        createdAt=run.created_at,
        finishedAt=run.finished_at,
    )


def _reject(code: str) -> ApiError:
    messages = {
        "invalid_query": "Câu truy vấn không hợp lệ.",
        "invalid_k": "Số kết quả yêu cầu không hợp lệ.",
        "too_many_documents": "Chỉ được lọc tối đa 50 tài liệu.",
    }
    return ApiError(422, code, messages.get(code, "Yêu cầu không hợp lệ."))


@router.post("/workspaces/{workspace_id}/retrieval/query", response_model=RetrievalResultDTO)
async def query_knowledge(
    workspace_id: UUID,
    body: RetrievalQueryRequest,
    request: Request,
    db: Database,
    claims: Claims,
):
    document_ids = list(dict.fromkeys(body.documentIds)) if body.documentIds is not None else None
    try:
        query = retrieval.validate(body.query, body.k, document_ids)
    except retrieval.RetrievalRejected as exc:
        raise _reject(exc.code) from None
    provider = embedder(request)

    # 1) authorize + meter the query embedding (committed even if the provider then fails).
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES) as scope:
        await usage.reserve(db, scope, QUERY_UNITS, unit_type=indexing.UNIT_TYPE)

    # 2) embed outside any transaction; failure degrades to lexical-only, never wider scope.
    vector = None
    try:
        result = await asyncio.to_thread(provider.embed, [query])
        if result.vectors and len(result.vectors[0]) == provider.dimension:
            vector = result.vectors[0]
    except embeddings.EmbeddingError:
        vector = None

    # 3) re-authorize and retrieve under RLS.
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES) as scope:
        chunks = await retrieval.retrieve(
            db,
            scope,
            query,
            document_ids=document_ids,
            k=body.k,
            query_vector=vector,
            model=provider.model if vector is not None else None,
            model_version=provider.version if vector is not None else None,
            max_distance=max_distance(request),
        )
    cited = citations.build_citations(chunks)
    audit(
        "retrieval.query",
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        result_count=len(chunks),
        mode="hybrid" if vector is not None else "lexical",
    )
    return RetrievalResultDTO(
        items=[item_dto(chunk, citation) for chunk, citation in zip(chunks, cited, strict=True)],
        model=provider.model,
        mode="hybrid" if vector is not None else "lexical",
        abstained=not chunks,
    )


@router.get("/workspaces/{workspace_id}/citations/{chunk_id}", response_model=CitationPreviewDTO)
async def get_citation(
    workspace_id: UUID,
    chunk_id: UUID,
    db: Database,
    claims: Claims,
    allow_superseded: Annotated[bool, Query(alias="allowSuperseded")] = False,
):
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES) as scope:
        preview = await citations.resolve_citation(
            db, scope, chunk_id, allow_superseded=allow_superseded
        )
    return CitationPreviewDTO(
        chunkId=preview.chunk_id,
        documentId=preview.document_id,
        versionId=preview.version_id,
        versionNo=preview.version_no,
        versionStatus=preview.version_status,
        fileName=preview.file_name,
        pageNo=preview.page_no,
        sectionPath=preview.section_path,
        charStart=preview.char_start,
        charEnd=preview.char_end,
        snippet=preview.snippet,
        text=preview.text,
        textSha256=preview.text_sha256,
        activatedAt=preview.activated_at,
    )


@router.post(
    "/workspaces/{workspace_id}/documents/{document_id}/embed",
    status_code=202,
    response_model=DocumentJobDTO,
)
async def embed_document(
    workspace_id: UUID,
    document_id: UUID,
    request: Request,
    db: Database,
    claims: Claims,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    provider = embedder(request)
    retried = False
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES) as scope:
        document = await load_document(db, workspace_id, document_id, lock=True)
        if not document.rights_attested:
            raise ApiError(
                409,
                "rights_attestation_required",
                "Tài liệu chưa có xác nhận quyền sử dụng nên không thể lập chỉ mục.",
            )
        if document.status != "uploaded" or document.active_version_id is None:
            raise ApiError(409, "document_not_ready", "Tài liệu chưa có phiên bản sẵn sàng.")
        runs = await db.scalar(
            select(func.count())
            .select_from(EmbeddingRun)
            .where(
                EmbeddingRun.workspace_id == workspace_id,
                EmbeddingRun.document_version_id == document.active_version_id,
            )
        )
        # Without a client key: one job per (version, model, version label, finished runs) so
        # repeated clicks share a job while a finished/failed run allows a fresh attempt.
        key = (
            job_service.client_idempotency_key(idempotency_key)
            if idempotency_key is not None
            else (
                f"{job_service.SYSTEM_KEY_PREFIX}document.embed:{document.active_version_id}:"
                f"{provider.model}:{provider.version}:{int(runs or 0)}"
            )
        )
        payload = {"documentId": str(document.id)}
        job, created = await job_service.enqueue_job(db, scope, "document.embed", payload, key)
        if not created and job.status == "failed":
            retried = job_service.request_retry(job)
            await db.flush()
    if created:
        audit(
            "document.embed",
            request_id=request_id(request),
            user_id=scope.user.id,
            workspace_id=workspace_id,
            document_id=document.id,
            job_id=job.id,
        )
    if created or retried:
        await dispatcher(request)(job)
    return DocumentJobDTO(document=document_dto(document), job=job_dto(job))


@router.get(
    "/workspaces/{workspace_id}/documents/{document_id}/embedding-runs",
    response_model=EmbeddingRunListDTO,
)
async def list_embedding_runs(
    workspace_id: UUID, document_id: UUID, request: Request, db: Database, claims: Claims
):
    provider = embedder(request)
    async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES):
        document = await load_document(db, workspace_id, document_id)
        rows = (
            await db.scalars(
                select(EmbeddingRun)
                .join(
                    DocumentVersion,
                    (DocumentVersion.workspace_id == EmbeddingRun.workspace_id)
                    & (DocumentVersion.id == EmbeddingRun.document_version_id),
                )
                .where(
                    EmbeddingRun.workspace_id == workspace_id,
                    DocumentVersion.document_id == document.id,
                )
                .order_by(EmbeddingRun.created_at.desc())
                .limit(100)
            )
        ).all()
        return EmbeddingRunListDTO(
            items=[run_dto(run) for run in rows],
            currentModel=provider.model,
            currentVersion=provider.version,
        )
