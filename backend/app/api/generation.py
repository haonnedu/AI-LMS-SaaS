"""AI drafts with provenance, exam assembly/publication and Word/PDF exports (M4 AI half).

All routes are workspace-scoped, re-authorize through ``workspace_transaction`` and are limited
to teaching roles; unknown or cross-workspace IDs are 404. AI generation and exports run as
durable jobs (202 + job). Answer keys reach only teacher DTOs, through ``edu.exam_item_key``; the
student-view DTO classes have no key or explanation fields at all. Prompts, source text, object
keys and signed URLs are never logged or audited.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authoring import ApproveDTO, ChoiceDTO, RevisionDTO, revision_dto
from app.api.documents import object_store
from app.api.identity import ApiError, Claims, Database, ErrorDTO
from app.api.jobs import TEACHING_ROLES, JobDTO, dispatcher, job_dto, keyset, load_job, next_cursor
from app.api.workspace_access import WorkspaceScope, workspace_transaction
from app.core.audit import audit
from app.models.generation import Exam, ExamItem, ExamVersion, ExportJob, GenerationJob
from app.services import content as content_service
from app.services import exam_builder, exports, generation, llm, provenance
from app.services import jobs as job_service
from app.services.authoring_common import AuthoringError
from app.services.storage import MAX_DOWNLOAD_TTL

CONFLICT_STATES = frozenset({"23505", "23503", "23514", "40001", "40P01"})
Purpose = Literal["lesson_plan", "study_guide", "questions"]
Cognitive = Literal["remember", "understand", "apply", "analyze"]
ValidationStatus = Literal["pending", "valid", "invalid", "failed"]
ExamStatus = Literal["draft", "published", "archived"]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=200)]
Points = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- Generation DTOs ------------------------------------------------------------------------


class GenerationRequestDTO(Strict):
    purpose: Purpose
    contentItemId: UUID | None = None
    curriculumUnitId: UUID
    grade: Annotated[int, Field(ge=1, le=12)]
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    objectives: list[Annotated[str, StringConstraints(min_length=1, max_length=500)]] = Field(
        min_length=1, max_length=20
    )
    durationMinutes: Annotated[int, Field(ge=1, le=600)] | None = None
    documentIds: list[UUID] | None = Field(default=None, max_length=50)
    count: Annotated[int, Field(ge=1, le=20)] | None = None
    cognitiveLevel: Cognitive | None = None
    title: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
        | None
    ) = None


class GenerationJobDTO(BaseModel):
    id: UUID
    backgroundJobId: UUID
    purpose: Purpose
    validationStatus: ValidationStatus
    provider: str
    model: str
    promptVersion: str
    inputTokens: int | None
    outputTokens: int | None
    reasons: list[str]
    errorCode: str | None
    contentItemId: UUID | None
    revisionNo: int | None
    questionIds: list[UUID]
    createdAt: datetime
    finishedAt: datetime | None


class GenerationAcceptedDTO(BaseModel):
    generationJob: GenerationJobDTO
    job: JobDTO


class ProvenanceSourceDTO(BaseModel):
    label: str
    chunkId: UUID | None
    documentId: UUID | None
    versionId: UUID | None
    pageNo: int | None
    sectionPath: str | None
    snippet: str | None
    status: Literal["active", "superseded", "withdrawn"]
    cited: bool


class ProvenanceDTO(BaseModel):
    contentItemId: UUID
    revisionNo: int
    generationJobId: UUID | None
    provider: str | None
    model: str | None
    promptVersion: str | None
    validationStatus: ValidationStatus | None
    sources: list[ProvenanceSourceDTO]


# ---- Exam DTOs ------------------------------------------------------------------------------


class ExamCreateDTO(Strict):
    title: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
        | None
    ) = None
    blueprintVersionId: UUID | None = None
    seed: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None
    questionIds: list[UUID] | None = Field(default=None, min_length=1, max_length=200)
    points: list[Points] | None = Field(default=None, min_length=1, max_length=200)


class MissingSlotDTO(BaseModel):
    partCode: str
    index: int
    reason: str
    curriculumUnitId: UUID
    cognitiveLevel: Cognitive
    difficulty: int | None


class SuggestedGenerationDTO(BaseModel):
    purpose: Literal["questions"]
    curriculumUnitId: UUID
    cognitiveLevel: Cognitive
    difficulty: int | None
    count: int


class SelectionReportDTO(BaseModel):
    ok: bool
    seed: str
    selected: int
    missingSlots: list[MissingSlotDTO]
    suggestedGeneration: list[SuggestedGenerationDTO]


class TeacherExamItemDTO(BaseModel):
    id: UUID
    position: int
    itemType: str
    stem: str
    choices: list[ChoiceDTO]
    points: Decimal
    sourceQuestionRevisionId: UUID | None
    curriculumUnitId: UUID | None
    cognitiveLevel: Cognitive | None
    correctKey: str | None
    explanation: str | None


class StudentExamItemDTO(BaseModel):
    """Student-safe: this class deliberately has NO key, rationale or explanation fields."""

    id: UUID
    position: int
    itemType: str
    stem: str
    choices: list[ChoiceDTO]
    points: Decimal


class ExamVersionSummaryDTO(BaseModel):
    id: UUID
    versionNo: int
    status: ExamStatus
    totalPoints: Decimal
    contentHash: str | None
    blueprintVersionId: UUID | None
    publishedAt: datetime | None
    publishedByUserId: UUID | None
    createdAt: datetime


class ExamVersionDTO(ExamVersionSummaryDTO):
    items: list[TeacherExamItemDTO]


class StudentExamViewDTO(BaseModel):
    examId: UUID
    title: str
    versionNo: int
    status: ExamStatus
    totalPoints: Decimal
    items: list[StudentExamItemDTO]


class ExamDTO(BaseModel):
    id: UUID
    title: str
    status: ExamStatus
    blueprintVersionId: UUID | None
    currentVersionId: UUID | None
    createdByUserId: UUID
    createdAt: datetime
    updatedAt: datetime


class ExamDetailDTO(ExamDTO):
    versions: list[ExamVersionSummaryDTO]
    currentVersion: ExamVersionDTO | None
    selectionReport: SelectionReportDTO | None = None


class ExamListDTO(BaseModel):
    items: list[ExamDTO]
    nextCursor: str | None


# ---- Export DTOs ----------------------------------------------------------------------------


class ExportRequestDTO(Strict):
    contentRevisionId: UUID | None = None
    examVersionId: UUID | None = None
    format: Literal["docx", "pdf"]
    audience: Literal["teacher", "student"]


class ExportJobDTO(BaseModel):
    id: UUID
    backgroundJobId: UUID
    contentRevisionId: UUID | None
    examVersionId: UUID | None
    format: Literal["docx", "pdf"]
    audience: Literal["teacher", "student"]
    status: Literal["queued", "succeeded", "failed"]
    errorCode: str | None
    createdAt: datetime
    finishedAt: datetime | None
    downloadUrl: str | None = None
    downloadExpiresAt: datetime | None = None


class ExportAcceptedDTO(BaseModel):
    exportJob: ExportJobDTO
    job: JobDTO


router = APIRouter(
    prefix="/v1",
    tags=["generation"],
    responses={status: {"model": ErrorDTO} for status in (401, 403, 404, 409, 422, 429, 503)},
)


# ---- Helpers --------------------------------------------------------------------------------


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or ""


@asynccontextmanager
async def tenant(
    db: AsyncSession, claims: dict, workspace_id: UUID
) -> AsyncIterator[WorkspaceScope]:
    """Teaching-role transaction mapping service errors and DB races to the error envelope."""
    try:
        async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES) as scope:
            yield scope
    except AuthoringError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) in CONFLICT_STATES:
            raise ApiError(
                409,
                "concurrent_update",
                "Dữ liệu vừa được thay đổi hoặc không còn hợp lệ. Vui lòng tải lại và thử lại.",
            ) from None
        raise


def generation_dto(generation_job: GenerationJob) -> GenerationJobDTO:
    output = generation_job.output or {}
    result = output if isinstance(output, dict) else {}
    return GenerationJobDTO(
        id=generation_job.id,
        backgroundJobId=generation_job.background_job_id,
        purpose=generation_job.purpose,
        validationStatus=generation_job.validation_status,
        provider=generation_job.provider,
        model=generation_job.model,
        promptVersion=generation_job.prompt_version,
        inputTokens=generation_job.input_tokens,
        outputTokens=generation_job.output_tokens,
        reasons=[str(r) for r in result.get("reasons", [])][:20],
        errorCode=result.get("errorCode"),
        contentItemId=None,
        revisionNo=None,
        questionIds=[UUID(q) for q in result.get("questionIds", [])],
        createdAt=generation_job.created_at,
        finishedAt=generation_job.finished_at,
    )


def _with_job_result(dto: GenerationJobDTO, job) -> GenerationJobDTO:
    result = job.result if isinstance(job.result, dict) else {}
    item = result.get("contentItemId")
    return dto.model_copy(
        update={
            "contentItemId": UUID(item) if item else None,
            "revisionNo": result.get("revisionNo"),
        }
    )


def exam_dto(exam: Exam) -> ExamDTO:
    return ExamDTO(
        id=exam.id,
        title=exam.title,
        status=exam.status,
        blueprintVersionId=exam.blueprint_version_id,
        currentVersionId=exam.current_version_id,
        createdByUserId=exam.created_by_user_id,
        createdAt=exam.created_at,
        updatedAt=exam.updated_at,
    )


def version_summary(version: ExamVersion) -> ExamVersionSummaryDTO:
    return ExamVersionSummaryDTO(
        id=version.id,
        versionNo=version.version_no,
        status=version.status,
        totalPoints=Decimal(version.total_points),
        contentHash=bytes(version.content_hash).hex() if version.content_hash else None,
        blueprintVersionId=version.blueprint_version_id,
        publishedAt=version.published_at,
        publishedByUserId=version.published_by_user_id,
        createdAt=version.created_at,
    )


async def teacher_item(db, item: ExamItem) -> TeacherExamItemDTO:
    return TeacherExamItemDTO(
        id=item.id,
        position=item.position,
        itemType=item.item_type,
        stem=item.stem,
        choices=[ChoiceDTO(**choice) for choice in item.choices],
        points=Decimal(item.points),
        sourceQuestionRevisionId=item.source_question_revision_id,
        curriculumUnitId=item.curriculum_unit_id,
        cognitiveLevel=item.cognitive_level,
        correctKey=await exam_builder.read_item_key(db, item.id),
        explanation=await exam_builder.read_item_explanation(db, item.id),
    )


def student_item(item: ExamItem) -> StudentExamItemDTO:
    return StudentExamItemDTO(
        id=item.id,
        position=item.position,
        itemType=item.item_type,
        stem=item.stem,
        choices=[ChoiceDTO(**choice) for choice in item.choices],
        points=Decimal(item.points),
    )


async def version_detail(db, version: ExamVersion) -> ExamVersionDTO:
    items = await exam_builder.load_items(db, version)
    return ExamVersionDTO(
        **version_summary(version).model_dump(),
        items=[await teacher_item(db, item) for item in items],
    )


async def exam_detail(db, exam: Exam, report=None) -> ExamDetailDTO:
    versions = await exam_builder.list_versions(db, exam)
    current = next((v for v in versions if v.id == exam.current_version_id), None)
    return ExamDetailDTO(
        **exam_dto(exam).model_dump(),
        versions=[version_summary(v) for v in versions],
        currentVersion=await version_detail(db, current) if current is not None else None,
        selectionReport=SelectionReportDTO(**report.as_dict()) if report is not None else None,
    )


def export_dto(export: ExportJob, url: str | None = None, expires=None) -> ExportJobDTO:
    return ExportJobDTO(
        id=export.id,
        backgroundJobId=export.background_job_id,
        contentRevisionId=export.content_revision_id,
        examVersionId=export.exam_version_id,
        format=export.format,
        audience=export.audience,
        status=export.status,
        errorCode=export.error_code,
        createdAt=export.created_at,
        finishedAt=export.finished_at,
        downloadUrl=url,
        downloadExpiresAt=expires,
    )


def _payload(body: GenerationRequestDTO) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True)
    for key in ("contentItemId", "curriculumUnitId"):
        if key in data:
            data[key] = str(data[key])
    if "documentIds" in data:
        data["documentIds"] = [str(d) for d in data["documentIds"]]
    return data


# ---- Generation -----------------------------------------------------------------------------


@router.post(
    "/workspaces/{workspace_id}/generation/drafts",
    status_code=202,
    response_model=GenerationAcceptedDTO,
)
async def request_draft(
    workspace_id: UUID,
    body: GenerationRequestDTO,
    request: Request,
    db: Database,
    claims: Claims,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    key = job_service.client_idempotency_key(idempotency_key)
    settings = request.app.state.settings
    async with tenant(db, claims, workspace_id) as scope:
        if not llm.provider_ready(settings):
            raise ApiError(
                503,
                "ai_unavailable",
                "Tính năng soạn bằng AI chưa sẵn sàng. Bạn vẫn có thể soạn thủ công.",
            )
        generation_job, job, created = await generation.enqueue_generation(
            db, scope, _payload(body), settings=settings, idempotency_key=key
        )
        dto = GenerationAcceptedDTO(
            generationJob=_with_job_result(generation_dto(generation_job), job), job=job_dto(job)
        )
    if created:
        audit(
            "generation.requested",
            request_id=request_id(request),
            user_id=scope.user.id,
            workspace_id=workspace_id,
            job_id=job.id,
            purpose=generation_job.purpose,
        )
        await dispatcher(request)(job)
    return dto


@router.get(
    "/workspaces/{workspace_id}/generation/jobs/{generation_id}",
    response_model=GenerationJobDTO,
)
async def get_generation_job(workspace_id: UUID, generation_id: UUID, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id):
        generation_job = await generation.load_generation(db, workspace_id, generation_id)
        job = await load_job(db, workspace_id, generation_job.background_job_id)
        return _with_job_result(generation_dto(generation_job), job)


@router.get(
    "/workspaces/{workspace_id}/content-items/{item_id}/revisions/{revision_no}/provenance",
    response_model=ProvenanceDTO,
)
async def get_provenance(
    workspace_id: UUID, item_id: UUID, revision_no: int, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        item = await content_service.load_item(db, workspace_id, item_id)
        revision = await content_service.load_revision(db, item, revision_no)
        result = await provenance.revision_provenance(db, scope, revision)
        return ProvenanceDTO(
            contentItemId=item.id,
            revisionNo=revision.revision_no,
            generationJobId=result.generation_job_id,
            provider=result.provider,
            model=result.model,
            promptVersion=result.prompt_version,
            validationStatus=result.validation_status,
            sources=[
                ProvenanceSourceDTO(
                    label=s.label,
                    chunkId=s.chunk_id,
                    documentId=s.document_id,
                    versionId=s.version_id,
                    pageNo=s.page_no,
                    sectionPath=s.section_path,
                    snippet=s.snippet,
                    status=s.status,
                    cited=s.cited,
                )
                for s in result.sources
            ],
        )


@router.post(
    "/workspaces/{workspace_id}/content-items/{item_id}/revisions/{revision_no}"
    "/approve-with-provenance",
    response_model=RevisionDTO,
)
async def approve_with_provenance(
    workspace_id: UUID,
    item_id: UUID,
    revision_no: int,
    request: Request,
    db: Database,
    claims: Claims,
    body: ApproveDTO | None = None,
):
    comment = body.comment if body else None
    async with tenant(db, claims, workspace_id) as scope:
        item = await content_service.load_item(db, workspace_id, item_id, lock=True)
        revision = await content_service.load_revision(db, item, revision_no)
        await provenance.check_citations(db, scope, revision.body)
        revision = await content_service.approve(
            db, scope, item_id, revision_no, comment=comment or None
        )
        dto = revision_dto(revision)
    audit(
        "content.approved",
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        content_item_id=item_id,
        revision_no=revision_no,
        provenance_checked=True,
    )
    return dto


# ---- Exams ----------------------------------------------------------------------------------


@router.post("/workspaces/{workspace_id}/exams", status_code=201, response_model=ExamDetailDTO)
async def create_exam(
    workspace_id: UUID, body: ExamCreateDTO, request: Request, db: Database, claims: Claims
):
    from_blueprint = body.blueprintVersionId is not None
    if from_blueprint == (body.questionIds is not None):
        raise ApiError(
            422,
            "invalid_exam_source",
            "Cần chọn đúng một cách tạo đề: theo cấu trúc đề hoặc danh sách câu hỏi.",
        )
    if not from_blueprint:
        if body.title is None:
            raise ApiError(422, "invalid_title", "Cần nhập tiêu đề đề kiểm tra.")
        if body.points is None or len(body.points) != len(body.questionIds):
            raise ApiError(422, "invalid_points", "Cần nhập điểm cho từng câu hỏi.")
        if body.seed is not None:
            raise ApiError(422, "invalid_exam_source", "Seed chỉ dùng khi tạo đề theo cấu trúc.")
    report = None
    async with tenant(db, claims, workspace_id) as scope:
        if from_blueprint:
            exam, _, _, report = await exam_builder.create_exam_from_blueprint(
                db,
                scope,
                blueprint_version_id=body.blueprintVersionId,
                title=body.title,
                seed=body.seed,
            )
            if exam is None:
                shortage = SelectionReportDTO(**report.as_dict()).model_dump(mode="json")
                return JSONResponse(
                    status_code=409,
                    content={
                        "error": {
                            "code": "insufficient_pool",
                            "message": "Ngân hàng câu hỏi chưa đủ câu cho cấu trúc đề; "
                            "đề chưa được tạo.",
                            "selectionReport": shortage,
                        },
                        "requestId": request_id(request),
                    },
                    headers={"Cache-Control": "no-store"},
                )
        else:
            exam, _, _ = await exam_builder.create_exam_manual(
                db,
                scope,
                title=body.title,
                selections=list(zip(body.questionIds, body.points, strict=True)),
            )
        dto = await exam_detail(db, exam, report)
    audit(
        "exam.created",
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        exam_id=exam.id,
        source="blueprint" if from_blueprint else "manual",
    )
    return dto


@router.get("/workspaces/{workspace_id}/exams", response_model=ExamListDTO)
async def list_exams(
    workspace_id: UUID,
    db: Database,
    claims: Claims,
    cursor: Cursor = None,
    limit: Limit = 20,
    status: ExamStatus | None = None,
):
    async with tenant(db, claims, workspace_id):
        query = (
            exam_builder.exam_listing(workspace_id, status=status)
            .where(*keyset(Exam, cursor))
            .order_by(Exam.created_at.desc(), Exam.id.desc())
            .limit(limit + 1)
        )
        rows = list((await db.scalars(query)).all())
        return ExamListDTO(
            items=[exam_dto(exam) for exam in rows[:limit]], nextCursor=next_cursor(rows, limit)
        )


@router.get("/workspaces/{workspace_id}/exams/{exam_id}", response_model=ExamDetailDTO)
async def get_exam(workspace_id: UUID, exam_id: UUID, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id):
        exam = await exam_builder.load_exam(db, workspace_id, exam_id)
        return await exam_detail(db, exam)


@router.get(
    "/workspaces/{workspace_id}/exams/{exam_id}/versions/{version_no}/student-view",
    response_model=StudentExamViewDTO,
)
async def get_student_view(
    workspace_id: UUID, exam_id: UUID, version_no: int, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id):
        exam = await exam_builder.load_exam(db, workspace_id, exam_id)
        version = await exam_builder.load_version(db, exam, version_no)
        items = await exam_builder.load_items(db, version)
        return StudentExamViewDTO(
            examId=exam.id,
            title=exam.title,
            versionNo=version.version_no,
            status=version.status,
            totalPoints=Decimal(version.total_points),
            items=[student_item(item) for item in items],
        )


@router.post(
    "/workspaces/{workspace_id}/exams/{exam_id}/versions/{version_no}/publish",
    response_model=ExamDetailDTO,
)
async def publish_exam(
    workspace_id: UUID,
    exam_id: UUID,
    version_no: int,
    request: Request,
    db: Database,
    claims: Claims,
):
    async with tenant(db, claims, workspace_id) as scope:
        await exam_builder.publish_exam_version(db, scope, exam_id, version_no)
        exam = await exam_builder.load_exam(db, workspace_id, exam_id)
        dto = await exam_detail(db, exam)
    audit(
        "exam.published",
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        exam_id=exam_id,
        version_no=version_no,
    )
    return dto


@router.post("/workspaces/{workspace_id}/exams/{exam_id}/archive", response_model=ExamDTO)
async def archive_exam(
    workspace_id: UUID, exam_id: UUID, request: Request, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        exam = await exam_builder.archive_exam(db, scope, exam_id)
        dto = exam_dto(exam)
    audit(
        "exam.archived",
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        exam_id=exam_id,
    )
    return dto


# ---- Exports --------------------------------------------------------------------------------


@router.post(
    "/workspaces/{workspace_id}/exports", status_code=202, response_model=ExportAcceptedDTO
)
async def request_export(
    workspace_id: UUID,
    body: ExportRequestDTO,
    request: Request,
    db: Database,
    claims: Claims,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    key = job_service.client_idempotency_key(idempotency_key)
    async with tenant(db, claims, workspace_id) as scope:
        export, job, created = await exports.enqueue_export(
            db,
            scope,
            content_revision_id=body.contentRevisionId,
            exam_version_id=body.examVersionId,
            fmt=body.format,
            audience=body.audience,
            idempotency_key=key,
        )
        dto = ExportAcceptedDTO(exportJob=export_dto(export), job=job_dto(job))
    if created:
        audit(
            "export.requested",
            request_id=request_id(request),
            user_id=scope.user.id,
            workspace_id=workspace_id,
            export_id=export.id,
            job_id=job.id,
            format=export.format,
            audience=export.audience,
        )
        await dispatcher(request)(job)
    return dto


@router.get("/workspaces/{workspace_id}/exports/{export_id}", response_model=ExportJobDTO)
async def get_export(
    workspace_id: UUID, export_id: UUID, request: Request, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id):
        export = await exports.load_export(db, workspace_id, export_id)
    if export.status != "succeeded" or not export.object_key:
        return export_dto(export)
    url, expires = object_store(request).presign_get(
        export.object_key,
        file_name=exports.file_name(export),
        mime=exports.mime_for(export.format),
        ttl_seconds=MAX_DOWNLOAD_TTL,
    )
    return export_dto(export, url, expires)
