"""Teacher assignments, results, releases and grade overrides (ASSIGN-01, ASMT-06..09).

Routes live under ``/v1/workspaces/{workspace_id}`` and run inside ``workspace_transaction``
(membership + RLS context, staff roles only); class access is checked per assignment, so
invisible or cross-workspace IDs answer 404. Teacher views may include correct keys (read
through ``edu.exam_keys_for_scoring``); results and the CSV export carry scores only.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity import ApiError, Claims, Database, ErrorDTO
from app.api.workspace_access import WorkspaceScope, workspace_transaction
from app.core.audit import audit
from app.services import assignments as service
from app.services import overrides, releases
from app.services.assessment_common import STAFF_ROLES, AssessmentError
from app.services.classes import TeachingError

router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}",
    tags=["assignments"],
    responses={status: {"model": ErrorDTO} for status in (401, 403, 404, 409, 422, 503)},
)

AssignmentStatus = Literal["draft", "published", "closed", "archived"]
ScoreRelease = Literal["immediate", "after_close", "manual"]
SolutionRelease = Literal["never", "after_close", "manual"]


# ---- DTOs -----------------------------------------------------------------------------------


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AssignmentCreateDTO(_Input):
    examVersionId: UUID
    title: str = Field(min_length=1, max_length=300)
    instructions: str | None = Field(default=None, max_length=10000)
    opensAt: datetime
    closesAt: datetime | None = None
    timeLimitSeconds: int | None = Field(
        default=None, ge=service.MIN_TIME_LIMIT, le=service.MAX_TIME_LIMIT
    )
    maxAttempts: int = Field(default=1, ge=1, le=service.MAX_ATTEMPTS)
    timezone: str = Field(default=service.DEFAULT_TIMEZONE, min_length=1, max_length=64)
    scoreRelease: ScoreRelease = "manual"
    solutionRelease: SolutionRelease = "manual"


class ExtendDTO(_Input):
    closesAt: datetime


class OverrideDTO(_Input):
    score: Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
    reason: str = Field(min_length=1, max_length=overrides.MAX_REASON)


class AssignmentDTO(BaseModel):
    id: UUID
    workspaceId: UUID
    classId: UUID
    examVersionId: UUID
    title: str
    instructions: str | None
    opensAt: datetime
    closesAt: datetime | None
    timeLimitSeconds: int | None
    maxAttempts: int
    timezone: str
    status: AssignmentStatus
    scoreRelease: ScoreRelease
    solutionRelease: SolutionRelease
    scoresReleasedAt: datetime | None
    solutionsReleasedAt: datetime | None
    publishedAt: datetime | None
    createdAt: datetime


class AssignmentListDTO(BaseModel):
    items: list[AssignmentDTO]


class ScoreReleaseDTO(BaseModel):
    assignment: AssignmentDTO
    releasedGrades: int


class DenominatorsDTO(BaseModel):
    enrolled: int
    started: int
    submitted: int
    graded: int
    pending: int


GradingStatus = Literal["not_started", "not_submitted", "pending", "graded", "void"]


class ResultItemDTO(BaseModel):
    studentId: UUID
    displayName: str
    attemptId: UUID | None
    attemptNo: int | None
    status: Literal["not_started", "in_progress", "submitted", "graded"]
    score: Decimal | None
    maxScore: Decimal | None
    gradingStatus: GradingStatus
    submittedAt: datetime | None


class ResultsDTO(BaseModel):
    assignmentId: UUID
    generatedAt: datetime
    denominators: DenominatorsDTO
    items: list[ResultItemDTO]


class ChoiceDTO(BaseModel):
    key: str
    text: str


class TeacherItemDTO(BaseModel):
    itemId: UUID
    position: int
    stem: str
    choices: list[ChoiceDTO]
    points: Decimal
    correctKey: str | None
    selectedKey: str | None
    answerRevision: int
    awardedPoints: Decimal | None
    reason: str | None


class GradeRevisionDTO(BaseModel):
    revisionNo: int
    score: Decimal
    maxScore: Decimal
    approvalMode: Literal["automatic", "teacher"]
    isCurrent: bool
    reason: str | None
    approvedAt: datetime
    releasedAt: datetime | None


class TeacherAttemptDTO(BaseModel):
    id: UUID
    assignmentId: UUID
    studentId: UUID
    displayName: str
    attemptNo: int
    status: Literal["in_progress", "submitted", "graded", "void"]
    startedAt: datetime
    deadlineAt: datetime | None
    submittedAt: datetime | None
    submissionReason: Literal["student", "deadline", "teacher"] | None
    snapshotSha256: str | None
    gradingStatus: GradingStatus
    items: list[TeacherItemDTO]
    grades: list[GradeRevisionDTO]


class OverrideResultDTO(BaseModel):
    attemptId: UUID
    revisionNo: int
    score: Decimal
    maxScore: Decimal
    reason: str
    approvedAt: datetime
    released: bool


def assignment_dto(a) -> AssignmentDTO:
    return AssignmentDTO(
        id=a.id,
        workspaceId=a.workspace_id,
        classId=a.class_id,
        examVersionId=a.exam_version_id,
        title=a.title,
        instructions=a.instructions,
        opensAt=a.opens_at,
        closesAt=a.closes_at,
        timeLimitSeconds=a.time_limit_seconds,
        maxAttempts=a.max_attempts,
        timezone=a.timezone,
        status=a.status,
        scoreRelease=a.score_release,
        solutionRelease=a.solution_release,
        scoresReleasedAt=a.scores_released_at,
        solutionsReleasedAt=a.solutions_released_at,
        publishedAt=a.published_at,
        createdAt=a.created_at,
    )


def result_item_dto(row: service.ResultRow) -> ResultItemDTO:
    return ResultItemDTO(
        studentId=row.student_id,
        displayName=row.display_name,
        attemptId=row.attempt_id,
        attemptNo=row.attempt_no,
        status=row.status,
        score=row.score,
        maxScore=row.max_score,
        gradingStatus=row.grading_status,
        submittedAt=row.submitted_at,
    )


# ---- Helpers --------------------------------------------------------------------------------


def now_utc() -> datetime:
    return datetime.now(UTC)


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or ""


@asynccontextmanager
async def tenant(
    db: AsyncSession, claims: dict, workspace_id: UUID
) -> AsyncIterator[WorkspaceScope]:
    try:
        async with workspace_transaction(db, claims, workspace_id, roles=STAFF_ROLES) as scope:
            yield scope
    except (AssessmentError, TeachingError) as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None


def _audit(request: Request, scope: WorkspaceScope, event: str, assignment, **fields) -> None:
    audit(
        event,
        request_id=request_id(request),
        user_id=scope.user.id,
        workspace_id=scope.workspace.id,
        assignment_id=assignment.id,
        **fields,
    )


# ---- Routes ---------------------------------------------------------------------------------


@router.post("/classes/{class_id}/assignments", response_model=AssignmentDTO, status_code=201)
async def create_assignment(
    workspace_id: UUID,
    class_id: UUID,
    body: AssignmentCreateDTO,
    request: Request,
    db: Database,
    claims: Claims,
):
    async with tenant(db, claims, workspace_id) as scope:
        created = await service.create_assignment(
            db,
            scope,
            class_id,
            exam_version_id=body.examVersionId,
            title=body.title,
            instructions=body.instructions or None,
            opens_at=body.opensAt,
            closes_at=body.closesAt,
            time_limit_seconds=body.timeLimitSeconds,
            max_attempts=body.maxAttempts,
            timezone=body.timezone,
            score_release=body.scoreRelease,
            solution_release=body.solutionRelease,
        )
        _audit(request, scope, "assignment.create", created, class_id=class_id)
        return assignment_dto(created)


@router.get("/classes/{class_id}/assignments", response_model=AssignmentListDTO)
async def list_assignments(workspace_id: UUID, class_id: UUID, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id) as scope:
        items = await service.list_assignments(db, scope, class_id)
        return AssignmentListDTO(items=[assignment_dto(a) for a in items])


@router.get("/assignments/{assignment_id}", response_model=AssignmentDTO)
async def get_assignment(workspace_id: UUID, assignment_id: UUID, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id) as scope:
        return assignment_dto(await service.get_assignment(db, scope, assignment_id))


@router.post("/assignments/{assignment_id}/publish", response_model=AssignmentDTO)
async def publish(
    workspace_id: UUID, assignment_id: UUID, request: Request, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        assignment = await service.publish(db, scope, assignment_id, now_utc())
        _audit(request, scope, "assignment.publish", assignment)
        return assignment_dto(assignment)


@router.post("/assignments/{assignment_id}/close", response_model=AssignmentDTO)
async def close(
    workspace_id: UUID, assignment_id: UUID, request: Request, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        assignment = await service.close(db, scope, assignment_id, now_utc())
        _audit(request, scope, "assignment.close", assignment)
        return assignment_dto(assignment)


@router.post("/assignments/{assignment_id}/extend", response_model=AssignmentDTO)
async def extend(
    workspace_id: UUID,
    assignment_id: UUID,
    body: ExtendDTO,
    request: Request,
    db: Database,
    claims: Claims,
):
    async with tenant(db, claims, workspace_id) as scope:
        assignment = await service.extend(db, scope, assignment_id, body.closesAt, now_utc())
        _audit(request, scope, "assignment.extend", assignment, closes_at=body.closesAt)
        return assignment_dto(assignment)


@router.post("/assignments/{assignment_id}/archive", response_model=AssignmentDTO)
async def archive(
    workspace_id: UUID, assignment_id: UUID, request: Request, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        assignment = await service.archive(db, scope, assignment_id, now_utc())
        _audit(request, scope, "assignment.archive", assignment)
        return assignment_dto(assignment)


@router.post("/assignments/{assignment_id}/release-scores", response_model=ScoreReleaseDTO)
async def release_scores(
    workspace_id: UUID, assignment_id: UUID, request: Request, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        assignment = await service.get_assignment(db, scope, assignment_id, for_update=True)
        released = await releases.release_scores(db, assignment, now_utc())
        _audit(request, scope, "assignment.release_scores", assignment, released=released)
        return ScoreReleaseDTO(assignment=assignment_dto(assignment), releasedGrades=released)


@router.post("/assignments/{assignment_id}/release-solutions", response_model=AssignmentDTO)
async def release_solutions(
    workspace_id: UUID, assignment_id: UUID, request: Request, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        assignment = await service.get_assignment(db, scope, assignment_id, for_update=True)
        changed = await releases.release_solutions(db, assignment, now_utc())
        if changed:
            _audit(request, scope, "assignment.release_solutions", assignment)
        return assignment_dto(assignment)


@router.get("/assignments/{assignment_id}/results", response_model=ResultsDTO)
async def results(workspace_id: UUID, assignment_id: UUID, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id) as scope:
        assignment, denominators, rows = await service.results(db, scope, assignment_id)
        return ResultsDTO(
            assignmentId=assignment.id,
            generatedAt=now_utc(),
            denominators=DenominatorsDTO(**denominators.__dict__),
            items=[result_item_dto(row) for row in rows],
        )


@router.get("/assignments/{assignment_id}/results/export.csv")
async def export_results(
    workspace_id: UUID, assignment_id: UUID, request: Request, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        assignment, _, rows = await service.results(db, scope, assignment_id)
        _audit(request, scope, "assignment.results_export", assignment, rows=len(rows))
    return Response(
        content=service.results_csv(rows).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="ket-qua-{assignment.id}.csv"',
        },
    )


@router.get("/assignments/{assignment_id}/attempts/{attempt_id}", response_model=TeacherAttemptDTO)
async def teacher_attempt(
    workspace_id: UUID, assignment_id: UUID, attempt_id: UUID, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        view = await service.teacher_attempt(db, scope, assignment_id, attempt_id)
        attempt = view.attempt
        snapshot = attempt.submitted_snapshot_sha256
        return TeacherAttemptDTO(
            id=attempt.id,
            assignmentId=attempt.assignment_id,
            studentId=attempt.student_id,
            displayName=view.display_name,
            attemptNo=attempt.attempt_no,
            status=attempt.status,
            startedAt=attempt.started_at,
            deadlineAt=attempt.deadline_at,
            submittedAt=attempt.submitted_at,
            submissionReason=attempt.submission_reason,
            snapshotSha256=bytes(snapshot).hex() if snapshot else None,
            gradingStatus=view.grading_status,
            items=[
                TeacherItemDTO(
                    itemId=item.item_id,
                    position=item.position,
                    stem=item.stem,
                    choices=[
                        ChoiceDTO(key=str(c["key"]), text=str(c["text"] or ""))
                        for c in item.choices
                    ],
                    points=item.points,
                    correctKey=item.correct_key,
                    selectedKey=item.selected_key,
                    answerRevision=item.answer_revision,
                    awardedPoints=item.awarded_points,
                    reason=item.reason,
                )
                for item in view.items
            ],
            grades=[
                GradeRevisionDTO(
                    revisionNo=g.revision_no,
                    score=g.score,
                    maxScore=g.max_score,
                    approvalMode=g.approval_mode,
                    isCurrent=g.is_current,
                    reason=g.reason,
                    approvedAt=g.approved_at,
                    releasedAt=g.released_at,
                )
                for g in view.grades
            ],
        )


@router.post(
    "/assignments/{assignment_id}/attempts/{attempt_id}/override",
    response_model=OverrideResultDTO,
    status_code=201,
)
async def override_grade(
    workspace_id: UUID,
    assignment_id: UUID,
    attempt_id: UUID,
    body: OverrideDTO,
    request: Request,
    db: Database,
    claims: Claims,
):
    async with tenant(db, claims, workspace_id) as scope:
        assignment = await service.get_assignment(db, scope, assignment_id)
        outcome = await overrides.override_grade(
            db,
            scope,
            assignment,
            attempt_id,
            score=body.score,
            reason=body.reason,
            now=now_utc(),
            request_id=request_id(request),
        )
        return OverrideResultDTO(
            attemptId=outcome.attempt_id,
            revisionNo=outcome.revision_no,
            score=outcome.score,
            maxScore=outcome.max_score,
            reason=outcome.reason,
            approvedAt=outcome.approved_at,
            released=False,
        )
