"""Manual authoring API: lesson plans/study guides, question bank, exam blueprints (M4 core).

All routes are workspace-scoped, re-authorize through ``workspace_transaction`` and are limited
to teaching roles (owner/admin/teacher); unknown or cross-workspace IDs are 404. Nothing here
calls an AI provider, so authoring keeps working during a provider outage.

Answer keys: the teacher question DTO reads ``correctKey`` only via ``edu.question_key``; the
student CSV export is a separate code path that never references keys or explanations.
"""

import codecs
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import and_, or_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity import ApiError, Claims, Database, ErrorDTO
from app.api.jobs import TEACHING_ROLES, encode_cursor, keyset, next_cursor
from app.api.jobs import decode_cursor as _decode_cursor
from app.api.workspace_access import WorkspaceScope, workspace_transaction
from app.core.audit import audit
from app.models.authoring import (
    Blueprint,
    BlueprintVersion,
    ContentItem,
    ContentRevision,
    Question,
    QuestionRevision,
)
from app.services import blueprints as blueprint_service
from app.services import content as content_service
from app.services import question_bank as bank
from app.services.authoring_common import AuthoringError, RevisionConflict

MAX_IMPORT_BYTES = 2 * 1024 * 1024
CONFLICT_STATES = frozenset({"23505", "23503", "23514", "40001", "40P01"})

ContentKind = Literal["lesson_plan", "study_guide"]
ItemStatus = Literal["draft", "in_review", "published", "archived"]
RevisionStatus = Literal["draft", "in_review", "approved", "published", "archived"]
Audience = Literal["teacher", "student"]
Cognitive = Literal["remember", "understand", "apply", "analyze"]
QuestionStatus = Literal["draft", "active", "retired"]
BlueprintStatus = Literal["draft", "validated", "published", "archived"]
ChoiceKey = Literal["A", "B", "C", "D", "E"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=200)]
RevisionNo = Annotated[int, Field(ge=0, le=1_000_000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- Content DTOs ---------------------------------------------------------------------------


class ContentCreateDTO(Strict):
    kind: ContentKind
    title: Title
    curriculumUnitId: UUID | None = None
    audience: Audience = "teacher"
    body: dict[str, Any] | None = None


class RevisionCreateDTO(Strict):
    body: dict[str, Any]
    expectedRevisionNo: RevisionNo
    audience: Audience | None = None


class DraftSaveDTO(Strict):
    body: dict[str, Any]
    expectedRevisionNo: RevisionNo


class SubmitDTO(Strict):
    assignedToUserId: UUID | None = None


class ApproveDTO(Strict):
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None


class RevisionSummaryDTO(BaseModel):
    id: UUID
    revisionNo: int
    status: RevisionStatus
    audience: Audience
    bodySha256: str
    basedOnRevisionId: UUID | None
    createdByUserId: UUID
    reviewedByUserId: UUID | None
    reviewedAt: datetime | None
    publishedAt: datetime | None
    createdAt: datetime
    updatedAt: datetime


class RevisionDTO(RevisionSummaryDTO):
    body: dict[str, Any]


class RevisionListDTO(BaseModel):
    items: list[RevisionSummaryDTO]


class ContentItemDTO(BaseModel):
    id: UUID
    kind: ContentKind
    title: str
    status: ItemStatus
    curriculumUnitId: UUID | None
    latestRevisionNo: int
    currentRevisionId: UUID | None
    createdByUserId: UUID
    createdAt: datetime
    updatedAt: datetime


class ContentItemDetailDTO(ContentItemDTO):
    latestRevision: RevisionDTO | None
    currentRevision: RevisionDTO | None


class ContentItemListDTO(BaseModel):
    items: list[ContentItemDTO]
    nextCursor: str | None


class DraftSavedDTO(BaseModel):
    revisionNo: int
    bodySha256: str
    savedAt: datetime


# ---- Question DTOs --------------------------------------------------------------------------


class ChoiceDTO(Strict):
    key: ChoiceKey
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class CitationDTO(Strict):
    chunkId: UUID
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class QuestionWriteDTO(Strict):
    itemType: Literal["single_choice"] = "single_choice"
    stem: Annotated[str, StringConstraints(min_length=1, max_length=10000)]
    choices: list[ChoiceDTO] = Field(min_length=3, max_length=5)
    correctKey: ChoiceKey | None = None
    rationale: Annotated[str, StringConstraints(max_length=10000)] | None = None
    explanation: Annotated[str, StringConstraints(max_length=10000)] | None = None
    difficulty: Annotated[int, Field(ge=1, le=5)] | None = None
    cognitiveLevel: Cognitive
    curriculumUnitId: UUID | None = None
    objectiveUnitIds: list[UUID] = Field(default_factory=list, max_length=20)
    sourceCitations: list[CitationDTO] = Field(default_factory=list, max_length=50)


class QuestionUpdateDTO(QuestionWriteDTO):
    expectedRevisionNo: RevisionNo | None = None


class KeyDTO(Strict):
    correctKey: ChoiceKey
    rationale: Annotated[str, StringConstraints(max_length=10000)] | None = None


class QuestionSummaryDTO(BaseModel):
    id: UUID
    itemType: str
    status: QuestionStatus
    stem: str
    difficulty: int | None
    cognitiveLevel: Cognitive
    curriculumUnitId: UUID | None
    revisionNo: int
    createdAt: datetime
    updatedAt: datetime


class StudentQuestionDTO(BaseModel):
    """Student-safe projection for later delivery work: no key, rationale or explanation."""

    id: UUID
    itemType: str
    stem: str
    choices: list[ChoiceDTO]


class TeacherQuestionDTO(QuestionSummaryDTO):
    revisionId: UUID
    choices: list[ChoiceDTO]
    correctKey: ChoiceKey | None
    explanation: str | None
    objectiveUnitIds: list[UUID]
    sourceCitations: list[CitationDTO]


class QuestionListDTO(BaseModel):
    items: list[QuestionSummaryDTO]
    nextCursor: str | None


class ImportErrorDTO(BaseModel):
    row: int
    code: str
    message: str


class ImportDuplicateDTO(BaseModel):
    row: int
    stemSha256: str
    duplicateOfRow: int | None
    existingQuestionId: UUID | None


class ImportResultDTO(BaseModel):
    created: int
    createdIds: list[UUID]
    duplicates: list[ImportDuplicateDTO]
    errors: list[ImportErrorDTO]


# ---- Blueprint DTOs -------------------------------------------------------------------------


class BlueprintCreateDTO(Strict):
    title: Title
    subjectId: UUID
    grade: Annotated[int, Field(ge=1, le=12)]
    programYear: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}$")] = "2018"
    examKind: Literal["periodic", "mock"]
    durationMinutes: Annotated[int, Field(ge=1, le=600)]
    totalPoints: Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)]
    effectiveYear: Annotated[int, Field(ge=2000, le=2100)]
    provenance: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    body: dict[str, Any] | None = None


class VersionCreateDTO(Strict):
    body: dict[str, Any]
    expectedVersionNo: RevisionNo | None = None


class IssueDTO(BaseModel):
    code: str
    message: str
    path: str


class ValidationReportDTO(BaseModel):
    ok: bool
    errors: list[IssueDTO]
    warnings: list[IssueDTO]


class BlueprintVersionSummaryDTO(BaseModel):
    id: UUID
    blueprintId: UUID
    versionNo: int
    status: BlueprintStatus
    bodySha256: str
    validationReport: ValidationReportDTO
    createdByUserId: UUID
    createdAt: datetime
    validatedAt: datetime | None
    publishedAt: datetime | None
    publishedByUserId: UUID | None


class BlueprintVersionDTO(BlueprintVersionSummaryDTO):
    body: dict[str, Any]


class BlueprintDTO(BaseModel):
    id: UUID
    title: str
    subjectId: UUID
    grade: int
    programYear: str
    examKind: Literal["periodic", "mock"]
    durationMinutes: int
    totalPoints: Decimal
    status: BlueprintStatus
    currentVersionId: UUID | None
    latestVersionNo: int
    effectiveYear: int
    originKind: str
    provenance: str
    createdAt: datetime
    updatedAt: datetime


class BlueprintDetailDTO(BlueprintDTO):
    versions: list[BlueprintVersionSummaryDTO]
    latestVersion: BlueprintVersionDTO | None


class BlueprintListDTO(BaseModel):
    items: list[BlueprintDTO]
    nextCursor: str | None


router = APIRouter(
    prefix="/v1",
    tags=["authoring"],
    responses={status: {"model": ErrorDTO} for status in (401, 403, 404, 409, 422, 503)},
)


# ---- Mapping helpers ------------------------------------------------------------------------


def _hex(value) -> str:
    return bytes(value).hex()


def _revision_fields(revision: ContentRevision) -> dict[str, Any]:
    return dict(
        id=revision.id,
        revisionNo=revision.revision_no,
        status=revision.status,
        audience=revision.audience,
        bodySha256=_hex(revision.body_sha256),
        basedOnRevisionId=revision.based_on_revision_id,
        createdByUserId=revision.created_by_user_id,
        reviewedByUserId=revision.reviewed_by_user_id,
        reviewedAt=revision.reviewed_at,
        publishedAt=revision.published_at,
        createdAt=revision.created_at,
        updatedAt=revision.updated_at,
    )


def revision_dto(revision: ContentRevision) -> RevisionDTO:
    return RevisionDTO(**_revision_fields(revision), body=revision.body)


def item_fields(item: ContentItem) -> dict[str, Any]:
    return dict(
        id=item.id,
        kind=item.kind,
        title=item.title,
        status=item.status,
        curriculumUnitId=item.curriculum_unit_id,
        latestRevisionNo=item.latest_revision_no,
        currentRevisionId=item.current_revision_id,
        createdByUserId=item.created_by_user_id,
        createdAt=item.created_at,
        updatedAt=item.updated_at,
    )


def question_summary(question: Question, revision: QuestionRevision) -> QuestionSummaryDTO:
    return QuestionSummaryDTO(
        id=question.id,
        itemType=question.item_type,
        status=question.status,
        stem=revision.stem,
        difficulty=question.difficulty,
        cognitiveLevel=question.cognitive_level,
        curriculumUnitId=question.curriculum_unit_id,
        revisionNo=revision.revision_no,
        createdAt=question.created_at,
        updatedAt=question.updated_at,
    )


def teacher_question_dto(
    question: Question,
    revision: QuestionRevision,
    correct_key: str | None,
    objective_unit_ids: list[UUID],
) -> TeacherQuestionDTO:
    return TeacherQuestionDTO(
        **question_summary(question, revision).model_dump(),
        revisionId=revision.id,
        choices=[ChoiceDTO(**choice) for choice in revision.choices],
        correctKey=correct_key,
        explanation=revision.explanation,
        objectiveUnitIds=objective_unit_ids,
        sourceCitations=[CitationDTO(**c) for c in (question.source_citations or [])],
    )


def student_question_dto(question: Question, revision: QuestionRevision) -> StudentQuestionDTO:
    return StudentQuestionDTO(
        id=question.id,
        itemType=question.item_type,
        stem=revision.stem,
        choices=[ChoiceDTO(**choice) for choice in revision.choices],
    )


def blueprint_dto(blueprint: Blueprint) -> BlueprintDTO:
    return BlueprintDTO(
        id=blueprint.id,
        title=blueprint.title,
        subjectId=blueprint.subject_id,
        grade=blueprint.grade,
        programYear=blueprint.program_year,
        examKind=blueprint.exam_kind,
        durationMinutes=blueprint.duration_minutes,
        totalPoints=blueprint.total_points,
        status=blueprint.status,
        currentVersionId=blueprint.current_version_id,
        latestVersionNo=blueprint.latest_version_no,
        effectiveYear=blueprint.effective_year,
        originKind=blueprint.origin_kind,
        provenance=blueprint.provenance,
        createdAt=blueprint.created_at,
        updatedAt=blueprint.updated_at,
    )


def _version_fields(version: BlueprintVersion) -> dict[str, Any]:
    report = version.validation_report or {}
    return dict(
        id=version.id,
        blueprintId=version.blueprint_id,
        versionNo=version.version_no,
        status=version.status,
        bodySha256=_hex(version.body_sha256),
        validationReport=ValidationReportDTO(
            ok=bool(report.get("ok", False)),
            errors=report.get("errors", []),
            warnings=report.get("warnings", []),
        ),
        createdByUserId=version.created_by_user_id,
        createdAt=version.created_at,
        validatedAt=version.validated_at,
        publishedAt=version.published_at,
        publishedByUserId=version.published_by_user_id,
    )


def version_dto(version: BlueprintVersion) -> BlueprintVersionDTO:
    return BlueprintVersionDTO(**_version_fields(version), body=version.body)


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or ""


def conflict_response(request: Request, exc: RevisionConflict, field: str) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {"code": exc.code, "message": exc.message, field: exc.latest},
            "requestId": request_id(request),
        },
        headers={"Cache-Control": "no-store"},
    )


def _page_cursor(rows: list, limit: int, entity=lambda row: row) -> str | None:
    if len(rows) <= limit:
        return None
    last = entity(rows[limit - 1])
    return encode_cursor(last.created_at, last.id)


def decode_cursor(cursor: str):
    return _decode_cursor(cursor)


@asynccontextmanager
async def tenant(
    db: AsyncSession, claims: dict, workspace_id: UUID
) -> AsyncIterator[WorkspaceScope]:
    """Teaching-role transaction; maps service errors and DB races to the error envelope.

    ``RevisionConflict`` passes through (after rollback) so routes can add the latest number.
    """
    try:
        async with workspace_transaction(db, claims, workspace_id, roles=TEACHING_ROLES) as scope:
            yield scope
    except RevisionConflict:
        raise
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


# ---- Content items --------------------------------------------------------------------------


async def _item_detail(db, item: ContentItem) -> ContentItemDetailDTO:
    latest = await content_service.load_revision(db, item, item.latest_revision_no)
    current = await content_service.load_revision_by_id(db, item, item.current_revision_id)
    return ContentItemDetailDTO(
        **item_fields(item),
        latestRevision=revision_dto(latest),
        currentRevision=revision_dto(current) if current is not None else None,
    )


@router.post(
    "/workspaces/{workspace_id}/content-items",
    response_model=ContentItemDetailDTO,
    status_code=201,
)
async def create_content_item(
    workspace_id: UUID, body: ContentCreateDTO, request: Request, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        item, revision = await content_service.create_item(
            db,
            scope,
            kind=body.kind,
            title=body.title,
            curriculum_unit_id=body.curriculumUnitId,
            body=body.body,
            audience=body.audience,
        )
        dto = ContentItemDetailDTO(
            **item_fields(item), latestRevision=revision_dto(revision), currentRevision=None
        )
    audit(
        "content.created",
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        content_item_id=item.id,
    )
    return dto


@router.get("/workspaces/{workspace_id}/content-items", response_model=ContentItemListDTO)
async def list_content_items(
    workspace_id: UUID,
    db: Database,
    claims: Claims,
    kind: ContentKind | None = None,
    status: ItemStatus | None = None,
    cursor: Cursor = None,
    limit: Limit = 20,
):
    query = content_service.item_listing(workspace_id, kind=kind, status=status)
    query = query.where(*keyset(ContentItem, cursor)).order_by(
        ContentItem.created_at.desc(), ContentItem.id.desc()
    )
    async with tenant(db, claims, workspace_id):
        rows = list((await db.scalars(query.limit(limit + 1))).all())
        return ContentItemListDTO(
            items=[ContentItemDTO(**item_fields(row)) for row in rows[:limit]],
            nextCursor=next_cursor(rows, limit),
        )


@router.get(
    "/workspaces/{workspace_id}/content-items/{item_id}", response_model=ContentItemDetailDTO
)
async def get_content_item(workspace_id: UUID, item_id: UUID, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id):
        item = await content_service.load_item(db, workspace_id, item_id)
        return await _item_detail(db, item)


@router.get(
    "/workspaces/{workspace_id}/content-items/{item_id}/revisions",
    response_model=RevisionListDTO,
)
async def list_content_revisions(workspace_id: UUID, item_id: UUID, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id):
        item = await content_service.load_item(db, workspace_id, item_id)
        rows = await content_service.list_revisions(db, item)
        return RevisionListDTO(items=[RevisionSummaryDTO(**_revision_fields(r)) for r in rows])


@router.get(
    "/workspaces/{workspace_id}/content-items/{item_id}/revisions/{revision_no}",
    response_model=RevisionDTO,
)
async def get_content_revision(
    workspace_id: UUID, item_id: UUID, revision_no: int, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id):
        item = await content_service.load_item(db, workspace_id, item_id)
        return revision_dto(await content_service.load_revision(db, item, revision_no))


@router.post(
    "/workspaces/{workspace_id}/content-items/{item_id}/revisions",
    response_model=RevisionDTO,
    status_code=201,
)
async def create_content_revision(
    workspace_id: UUID,
    item_id: UUID,
    body: RevisionCreateDTO,
    request: Request,
    db: Database,
    claims: Claims,
):
    try:
        async with tenant(db, claims, workspace_id) as scope:
            revision = await content_service.create_revision(
                db,
                scope,
                item_id,
                expected_revision_no=body.expectedRevisionNo,
                body=body.body,
                audience=body.audience,
            )
            dto = revision_dto(revision)
    except RevisionConflict as exc:
        return conflict_response(request, exc, "latestRevisionNo")
    audit(
        "content.revision_created",
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        content_item_id=item_id,
        revision_no=dto.revisionNo,
    )
    return dto


@router.put(
    "/workspaces/{workspace_id}/content-items/{item_id}/draft", response_model=DraftSavedDTO
)
async def save_content_draft(
    workspace_id: UUID,
    item_id: UUID,
    body: DraftSaveDTO,
    request: Request,
    db: Database,
    claims: Claims,
):
    try:
        async with tenant(db, claims, workspace_id) as scope:
            revision = await content_service.save_draft(
                db, scope, item_id, expected_revision_no=body.expectedRevisionNo, body=body.body
            )
            dto = DraftSavedDTO(
                revisionNo=revision.revision_no,
                bodySha256=_hex(revision.body_sha256),
                savedAt=revision.updated_at,
            )
    except RevisionConflict as exc:
        return conflict_response(request, exc, "latestRevisionNo")
    return dto


async def _transition(
    request: Request,
    db,
    claims,
    workspace_id: UUID,
    item_id: UUID,
    revision_no: int,
    event: str,
    action,
) -> RevisionDTO:
    async with tenant(db, claims, workspace_id) as scope:
        revision = await action(scope)
        dto = revision_dto(revision)
    audit(
        event,
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        content_item_id=item_id,
        revision_no=revision_no,
    )
    return dto


@router.post(
    "/workspaces/{workspace_id}/content-items/{item_id}/revisions/{revision_no}/submit",
    response_model=RevisionDTO,
)
async def submit_content_revision(
    workspace_id: UUID,
    item_id: UUID,
    revision_no: int,
    request: Request,
    db: Database,
    claims: Claims,
    body: SubmitDTO | None = None,
):
    assignee = body.assignedToUserId if body else None
    return await _transition(
        request,
        db,
        claims,
        workspace_id,
        item_id,
        revision_no,
        "content.submitted",
        lambda scope: content_service.submit_for_review(
            db, scope, item_id, revision_no, assigned_to=assignee
        ),
    )


@router.post(
    "/workspaces/{workspace_id}/content-items/{item_id}/revisions/{revision_no}/approve",
    response_model=RevisionDTO,
)
async def approve_content_revision(
    workspace_id: UUID,
    item_id: UUID,
    revision_no: int,
    request: Request,
    db: Database,
    claims: Claims,
    body: ApproveDTO | None = None,
):
    comment = body.comment if body else None
    return await _transition(
        request,
        db,
        claims,
        workspace_id,
        item_id,
        revision_no,
        "content.approved",
        lambda scope: content_service.approve(
            db, scope, item_id, revision_no, comment=comment or None
        ),
    )


@router.post(
    "/workspaces/{workspace_id}/content-items/{item_id}/revisions/{revision_no}/publish",
    response_model=RevisionDTO,
)
async def publish_content_revision(
    workspace_id: UUID,
    item_id: UUID,
    revision_no: int,
    request: Request,
    db: Database,
    claims: Claims,
):
    return await _transition(
        request,
        db,
        claims,
        workspace_id,
        item_id,
        revision_no,
        "content.published",
        lambda scope: content_service.publish(db, scope, item_id, revision_no),
    )


# ---- Question bank --------------------------------------------------------------------------


def question_input(body: QuestionWriteDTO) -> bank.QuestionInput:
    return bank.QuestionInput(
        stem=body.stem,
        choices=[choice.model_dump() for choice in body.choices],
        cognitive_level=body.cognitiveLevel,
        difficulty=body.difficulty,
        correct_key=body.correctKey,
        rationale=body.rationale,
        explanation=body.explanation,
        curriculum_unit_id=body.curriculumUnitId,
        objective_unit_ids=tuple(body.objectiveUnitIds),
        source_citations=tuple(
            {"chunkId": str(c.chunkId), "label": c.label} for c in body.sourceCitations
        ),
        item_type=body.itemType,
    )


async def _teacher_detail(db, question: Question, revision: QuestionRevision):
    key = await bank.read_key(db, revision.id)
    objectives = await bank.objective_ids(db, question)
    return teacher_question_dto(question, revision, key, objectives)


def _audit_question(request: Request, event: str, scope, workspace_id: UUID, question_id: UUID):
    # Never log key values; IDs only.
    audit(
        event,
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        question_id=question_id,
    )


@router.post(
    "/workspaces/{workspace_id}/questions", response_model=TeacherQuestionDTO, status_code=201
)
async def create_question(
    workspace_id: UUID, body: QuestionWriteDTO, request: Request, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        question, revision = await bank.create_question(db, scope, question_input(body))
        dto = await _teacher_detail(db, question, revision)
    _audit_question(request, "question.created", scope, workspace_id, question.id)
    return dto


@router.get("/workspaces/{workspace_id}/questions", response_model=QuestionListDTO)
async def list_questions(
    workspace_id: UUID,
    db: Database,
    claims: Claims,
    unit_id: Annotated[UUID | None, Query(alias="unitId")] = None,
    difficulty: Annotated[int | None, Query(ge=1, le=5)] = None,
    cognitive_level: Annotated[Cognitive | None, Query(alias="cognitiveLevel")] = None,
    status: QuestionStatus | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    cursor: Cursor = None,
    limit: Limit = 20,
):
    query = bank.question_listing(
        workspace_id,
        unit_id=unit_id,
        difficulty=difficulty,
        cognitive_level=cognitive_level,
        status=status,
        search=q,
    )
    if cursor:
        created, row_id = decode_cursor(cursor)
        query = query.where(
            or_(
                Question.created_at < created,
                and_(Question.created_at == created, Question.id < row_id),
            )
        )
    query = query.order_by(Question.created_at.desc(), Question.id.desc()).limit(limit + 1)
    async with tenant(db, claims, workspace_id):
        rows = list((await db.execute(query)).all())
        return QuestionListDTO(
            items=[question_summary(question, revision) for question, revision in rows[:limit]],
            nextCursor=_page_cursor(rows, limit, lambda row: row[0]),
        )


@router.post("/workspaces/{workspace_id}/questions/import", response_model=ImportResultDTO)
async def import_questions(
    workspace_id: UUID,
    request: Request,
    db: Database,
    claims: Claims,
    content_type: Annotated[str | None, Header()] = None,
    content_length: Annotated[int | None, Header()] = None,
):
    media = (content_type or "").split(";", 1)[0].strip().lower()
    if media != "text/csv":
        raise ApiError(415, "unsupported_media_type", "Chỉ chấp nhận tệp CSV (text/csv).")
    if content_length is not None and content_length > MAX_IMPORT_BYTES:
        raise ApiError(413, "payload_too_large", "Tệp CSV vượt quá giới hạn 2 MB.")
    async with tenant(db, claims, workspace_id):  # authorize before accepting any bytes
        pass
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_IMPORT_BYTES:
            raise ApiError(413, "payload_too_large", "Tệp CSV vượt quá giới hạn 2 MB.")
    try:
        text_value = codecs.decode(bytes(raw), "utf-8")
    except UnicodeDecodeError:
        raise ApiError(422, "invalid_encoding", "Tệp CSV phải dùng bảng mã UTF-8.") from None
    async with tenant(db, claims, workspace_id) as scope:
        report = await bank.import_csv(db, scope, text_value)
    if report.created:
        audit(
            "question.imported",
            request_id=request_id(request),
            user_id=scope.user.id,
            workspace_id=workspace_id,
            created=len(report.created),
            duplicates=len(report.duplicates),
        )
    return ImportResultDTO(
        created=len(report.created),
        createdIds=report.created,
        duplicates=report.duplicates,
        errors=report.errors,
    )


@router.get("/workspaces/{workspace_id}/questions/export")
async def export_questions(
    workspace_id: UUID,
    db: Database,
    claims: Claims,
    audience: Audience,
):
    async with tenant(db, claims, workspace_id):
        if audience == "student":
            content = bank.student_csv(await bank.student_export_rows(db, workspace_id))
        else:
            content = bank.teacher_csv(await bank.teacher_export_rows(db, workspace_id))
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="questions-{audience}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/workspaces/{workspace_id}/questions/{question_id}", response_model=TeacherQuestionDTO)
async def get_question(workspace_id: UUID, question_id: UUID, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id):
        question = await bank.load_question(db, workspace_id, question_id)
        revision = await bank.load_current_revision(db, question)
        return await _teacher_detail(db, question, revision)


@router.put("/workspaces/{workspace_id}/questions/{question_id}", response_model=TeacherQuestionDTO)
async def update_question(
    workspace_id: UUID,
    question_id: UUID,
    body: QuestionUpdateDTO,
    request: Request,
    db: Database,
    claims: Claims,
):
    try:
        async with tenant(db, claims, workspace_id) as scope:
            question, revision = await bank.update_question(
                db,
                scope,
                question_id,
                question_input(body),
                expected_revision_no=body.expectedRevisionNo,
            )
            dto = await _teacher_detail(db, question, revision)
    except RevisionConflict as exc:
        return conflict_response(request, exc, "latestRevisionNo")
    _audit_question(request, "question.revised", scope, workspace_id, question_id)
    return dto


@router.put(
    "/workspaces/{workspace_id}/questions/{question_id}/key", response_model=TeacherQuestionDTO
)
async def set_question_key(
    workspace_id: UUID,
    question_id: UUID,
    body: KeyDTO,
    request: Request,
    db: Database,
    claims: Claims,
):
    async with tenant(db, claims, workspace_id) as scope:
        question, revision = await bank.set_key(
            db, scope, question_id, body.correctKey, body.rationale
        )
        dto = await _teacher_detail(db, question, revision)
    _audit_question(request, "question.key_set", scope, workspace_id, question_id)
    return dto


@router.post(
    "/workspaces/{workspace_id}/questions/{question_id}/retire",
    response_model=TeacherQuestionDTO,
)
async def retire_question(
    workspace_id: UUID, question_id: UUID, request: Request, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        question = await bank.retire(db, scope, question_id)
        revision = await bank.load_current_revision(db, question)
        dto = await _teacher_detail(db, question, revision)
    _audit_question(request, "question.retired", scope, workspace_id, question_id)
    return dto


# ---- Blueprints -----------------------------------------------------------------------------


async def _blueprint_detail(db, blueprint: Blueprint) -> BlueprintDetailDTO:
    versions = await blueprint_service.list_versions(db, blueprint)
    return BlueprintDetailDTO(
        **blueprint_dto(blueprint).model_dump(),
        versions=[BlueprintVersionSummaryDTO(**_version_fields(v)) for v in versions],
        latestVersion=version_dto(versions[0]) if versions else None,
    )


@router.post(
    "/workspaces/{workspace_id}/blueprints", response_model=BlueprintDetailDTO, status_code=201
)
async def create_blueprint(
    workspace_id: UUID, body: BlueprintCreateDTO, request: Request, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        blueprint = await blueprint_service.create_blueprint(
            db,
            scope,
            title=body.title,
            subject_id=body.subjectId,
            grade=body.grade,
            program_year=body.programYear,
            exam_kind=body.examKind,
            duration_minutes=body.durationMinutes,
            total_points=body.totalPoints,
            effective_year=body.effectiveYear,
            provenance=body.provenance,
        )
        versions = []
        if body.body is not None:
            versions.append(
                await blueprint_service.create_version(
                    db, scope, blueprint.id, body.body, blueprint=blueprint
                )
            )
        dto = BlueprintDetailDTO(
            **blueprint_dto(blueprint).model_dump(),
            versions=[BlueprintVersionSummaryDTO(**_version_fields(v)) for v in versions],
            latestVersion=version_dto(versions[0]) if versions else None,
        )
    audit(
        "blueprint.created",
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        blueprint_id=blueprint.id,
    )
    return dto


@router.get("/workspaces/{workspace_id}/blueprints", response_model=BlueprintListDTO)
async def list_blueprints(
    workspace_id: UUID,
    db: Database,
    claims: Claims,
    status: BlueprintStatus | None = None,
    cursor: Cursor = None,
    limit: Limit = 20,
):
    query = blueprint_service.blueprint_listing(workspace_id, status=status)
    query = query.where(*keyset(Blueprint, cursor)).order_by(
        Blueprint.created_at.desc(), Blueprint.id.desc()
    )
    async with tenant(db, claims, workspace_id):
        rows = list((await db.scalars(query.limit(limit + 1))).all())
        return BlueprintListDTO(
            items=[blueprint_dto(row) for row in rows[:limit]],
            nextCursor=next_cursor(rows, limit),
        )


@router.get(
    "/workspaces/{workspace_id}/blueprints/{blueprint_id}", response_model=BlueprintDetailDTO
)
async def get_blueprint(workspace_id: UUID, blueprint_id: UUID, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id):
        blueprint = await blueprint_service.load_blueprint(db, workspace_id, blueprint_id)
        return await _blueprint_detail(db, blueprint)


@router.post(
    "/workspaces/{workspace_id}/blueprints/{blueprint_id}/versions",
    response_model=BlueprintVersionDTO,
    status_code=201,
)
async def create_blueprint_version(
    workspace_id: UUID,
    blueprint_id: UUID,
    body: VersionCreateDTO,
    request: Request,
    db: Database,
    claims: Claims,
):
    try:
        async with tenant(db, claims, workspace_id) as scope:
            version = await blueprint_service.create_version(
                db, scope, blueprint_id, body.body, expected_version_no=body.expectedVersionNo
            )
            dto = version_dto(version)
    except RevisionConflict as exc:
        return conflict_response(request, exc, "latestVersionNo")
    audit(
        "blueprint.version_created",
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        blueprint_id=blueprint_id,
        version_no=dto.versionNo,
        valid=dto.validationReport.ok,
    )
    return dto


@router.post(
    "/workspaces/{workspace_id}/blueprints/{blueprint_id}/versions/{version_no}/validate",
    response_model=BlueprintVersionDTO,
)
async def validate_blueprint_version(
    workspace_id: UUID, blueprint_id: UUID, version_no: int, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        version = await blueprint_service.revalidate(db, scope, blueprint_id, version_no)
        return version_dto(version)


@router.post(
    "/workspaces/{workspace_id}/blueprints/{blueprint_id}/versions/{version_no}/publish",
    response_model=BlueprintVersionDTO,
)
async def publish_blueprint_version(
    workspace_id: UUID,
    blueprint_id: UUID,
    version_no: int,
    request: Request,
    db: Database,
    claims: Claims,
):
    async with tenant(db, claims, workspace_id) as scope:
        version = await blueprint_service.publish(db, scope, blueprint_id, version_no)
        dto = version_dto(version)
    audit(
        "blueprint.published",
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=workspace_id,
        blueprint_id=blueprint_id,
        version_no=version_no,
        body_sha256=dto.bodySha256,
    )
    return dto
