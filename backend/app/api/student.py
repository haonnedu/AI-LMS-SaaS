"""Student assignments and quiz attempts (ASSIGN-02, ASMT-01..07), for any active account.

Students are not workspace members, so these routes do NOT use ``workspace_transaction``.
Each request opens one transaction, applies only the verified identity (``current_user`` ->
``set_identity``) and calls the narrow SECURITY DEFINER functions of migration 0015, which
derive the student from that identity. IDs of other students' attempts answer 404.

None of the DTOs used before solution release has a key or explanation field. The results DTO
carries a nullable ``solution`` object that the database fills only after the teacher's
solution release; scores appear only from a released grade revision.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity import ApiError, Claims, Database, ErrorDTO, current_user
from app.services import attempts as service
from app.services import jobs as job_service
from app.services.assessment_common import AssessmentError

logger = logging.getLogger("eduvia.assessment")

router = APIRouter(
    prefix="/v1/student",
    tags=["student"],
    responses={status: {"model": ErrorDTO} for status in (401, 403, 404, 409, 422, 503)},
)

AttemptStatus = Literal["in_progress", "submitted", "graded", "void"]
Availability = Literal["resume", "open", "not_open_yet", "closed", "limit_reached", "done"]


# ---- DTOs (no correctKey / explanation fields) ----------------------------------------------


class ChoiceDTO(BaseModel):
    key: str
    text: str


class StudentAssignmentDTO(BaseModel):
    id: UUID
    workspaceId: UUID
    classId: UUID
    className: str
    title: str
    opensAt: datetime
    closesAt: datetime | None
    timeLimitSeconds: int | None
    maxAttempts: int
    timezone: str
    status: Literal["published", "closed"]
    attemptsUsed: int
    inProgressAttemptId: UUID | None
    latestAttemptId: UUID | None
    latestAttemptStatus: AttemptStatus | None
    availability: Availability
    serverNow: datetime


class StudentAssignmentListDTO(BaseModel):
    items: list[StudentAssignmentDTO]


class StudentAssignmentDetailDTO(StudentAssignmentDTO):
    instructions: str | None
    itemCount: int
    totalPoints: Decimal | None


class StartedAttemptDTO(BaseModel):
    attemptId: UUID
    created: bool
    status: AttemptStatus
    attemptNo: int
    startedAt: datetime
    deadlineAt: datetime | None
    serverNow: datetime


class AttemptItemDTO(BaseModel):
    itemId: UUID
    position: int
    stem: str
    choices: list[ChoiceDTO]
    points: Decimal
    selectedKey: str | None
    answerRevision: int
    clientSequence: int
    savedAt: datetime | None


class AttemptDTO(BaseModel):
    id: UUID
    assignmentId: UUID
    title: str
    attemptNo: int
    status: AttemptStatus
    startedAt: datetime
    deadlineAt: datetime | None
    submittedAt: datetime | None
    submissionReason: Literal["student", "deadline", "teacher"] | None
    snapshotSha256: str | None
    answerSequence: int
    serverNow: datetime
    items: list[AttemptItemDTO]


class AnswerDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selectedKey: str | None = Field(pattern=r"^[A-Z]$")
    expectedRevision: int = Field(ge=0, le=1_000_000)
    clientSequence: int = Field(ge=0, le=9_007_199_254_740_991)


class SavedAnswerDTO(BaseModel):
    answerRevision: int
    savedAt: datetime
    serverNow: datetime


class SubmissionDTO(BaseModel):
    status: AttemptStatus
    submittedAt: datetime
    snapshotSha256: str
    submissionReason: Literal["student", "deadline", "teacher"]
    replayed: bool


class ReleasedSolutionDTO(BaseModel):
    """Populated by the database only after the assignment's solution release."""

    correctKey: str | None
    explanation: str | None


class ResultItemDTO(BaseModel):
    itemId: UUID
    position: int
    selectedKey: str | None
    maxPoints: Decimal
    awardedPoints: Decimal | None
    solution: ReleasedSolutionDTO | None


class StudentResultDTO(BaseModel):
    attemptId: UUID
    assignmentId: UUID
    status: AttemptStatus
    submittedAt: datetime | None
    gradingStatus: Literal["not_submitted", "pending", "graded", "void"]
    scoreReleased: bool
    score: Decimal | None
    maxScore: Decimal | None
    releasedAt: datetime | None
    solutionsReleased: bool
    items: list[ResultItemDTO]


# DTOs a student receives before any release decision; they must never grow key fields.
PRE_RELEASE_DTOS = (
    ChoiceDTO,
    StudentAssignmentDTO,
    StudentAssignmentDetailDTO,
    StartedAttemptDTO,
    AttemptItemDTO,
    AttemptDTO,
    SavedAnswerDTO,
    SubmissionDTO,
)


def assignment_fields(a: service.StudentAssignment) -> dict[str, Any]:
    return {
        "id": a.assignment_id,
        "workspaceId": a.workspace_id,
        "classId": a.class_id,
        "className": a.class_name,
        "title": a.title,
        "opensAt": a.opens_at,
        "closesAt": a.closes_at,
        "timeLimitSeconds": a.time_limit_seconds,
        "maxAttempts": a.max_attempts,
        "timezone": a.timezone,
        "status": a.status,
        "attemptsUsed": a.attempts_used,
        "inProgressAttemptId": a.in_progress_attempt_id,
        "latestAttemptId": a.latest_attempt_id,
        "latestAttemptStatus": a.latest_attempt_status,
        "availability": a.availability,
        "serverNow": a.server_now,
    }


def result_dto(data: dict[str, Any]) -> StudentResultDTO:
    items = []
    for item in data.get("items") or []:
        solution = item.get("solution")
        items.append(
            ResultItemDTO(
                itemId=item["itemId"],
                position=item["position"],
                selectedKey=item.get("selectedKey"),
                maxPoints=Decimal(str(item["maxPoints"])),
                awardedPoints=(
                    Decimal(str(item["awardedPoints"]))
                    if item.get("awardedPoints") is not None
                    else None
                ),
                solution=(
                    ReleasedSolutionDTO(
                        correctKey=solution.get("correctKey"),
                        explanation=solution.get("explanation"),
                    )
                    if data.get("solutionsReleased") and isinstance(solution, dict)
                    else None
                ),
            )
        )
    released = bool(data.get("scoreReleased"))
    return StudentResultDTO(
        attemptId=data["attemptId"],
        assignmentId=data["assignmentId"],
        status=data["status"],
        submittedAt=data.get("submittedAt"),
        gradingStatus=data["gradingStatus"],
        scoreReleased=released,
        score=Decimal(str(data["score"])) if released and data.get("score") is not None else None,
        maxScore=(
            Decimal(str(data["maxScore"]))
            if released and data.get("maxScore") is not None
            else None
        ),
        releasedAt=data.get("releasedAt") if released else None,
        solutionsReleased=bool(data.get("solutionsReleased")),
        items=items,
    )


# ---- Helpers --------------------------------------------------------------------------------


@asynccontextmanager
async def student_transaction(db: AsyncSession, claims: dict) -> AsyncIterator[None]:
    """One transaction with the verified identity only (no workspace context)."""
    try:
        async with db.begin():
            await current_user(db, claims)
            yield
    except AssessmentError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None


def idempotency_key(raw: str | None) -> str:
    if raw is None:
        raise ApiError(422, "idempotency_key_required", "Cần gửi header Idempotency-Key.")
    return job_service.client_idempotency_key(raw)


async def dispatch_grading(job_id: UUID | None) -> None:
    """After commit; a broker failure leaves the job queued for the sweeper."""
    if job_id is None:
        return
    try:
        await asyncio.to_thread(job_service.send_job, job_id, "attempt.grade")
    except Exception as exc:
        logger.warning("grading_dispatch_failed", extra={"error_type": type(exc).__name__})


IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


# ---- Routes ---------------------------------------------------------------------------------


@router.get("/assignments", response_model=StudentAssignmentListDTO)
async def list_assignments(db: Database, claims: Claims):
    async with student_transaction(db, claims):
        items = await service.list_assignments(db)
    return StudentAssignmentListDTO(
        items=[StudentAssignmentDTO(**assignment_fields(a)) for a in items]
    )


@router.get("/assignments/{assignment_id}", response_model=StudentAssignmentDetailDTO)
async def assignment_detail(assignment_id: UUID, db: Database, claims: Claims):
    async with student_transaction(db, claims):
        a = await service.assignment_detail(db, assignment_id)
    return StudentAssignmentDetailDTO(
        **assignment_fields(a),
        instructions=a.instructions,
        itemCount=a.item_count or 0,
        totalPoints=a.total_points,
    )


@router.post(
    "/assignments/{assignment_id}/attempts",
    response_model=StartedAttemptDTO,
    responses={201: {"model": StartedAttemptDTO}},
)
async def start_attempt(
    assignment_id: UUID,
    request: Request,
    response: Response,
    db: Database,
    claims: Claims,
    key: IdempotencyKey = None,
):
    client_key = idempotency_key(key)
    consent_age = request.app.state.settings.privacy_consent_age
    async with student_transaction(db, claims):
        started = await service.start_attempt(
            db, assignment_id, client_key, consent_age=consent_age
        )
    response.status_code = 201 if started.created else 200
    return StartedAttemptDTO(
        attemptId=started.attempt_id,
        created=started.created,
        status=started.status,
        attemptNo=started.attempt_no,
        startedAt=started.started_at,
        deadlineAt=started.deadline_at,
        serverNow=started.server_now,
    )


@router.get("/attempts/{attempt_id}", response_model=AttemptDTO)
async def get_attempt(attempt_id: UUID, db: Database, claims: Claims):
    async with student_transaction(db, claims):
        view = await service.attempt_view(db, attempt_id)
    return AttemptDTO(
        id=view.attempt_id,
        assignmentId=view.assignment_id,
        title=view.title,
        attemptNo=view.attempt_no,
        status=view.status,
        startedAt=view.started_at,
        deadlineAt=view.deadline_at,
        submittedAt=view.submitted_at,
        submissionReason=view.submission_reason,
        snapshotSha256=view.snapshot_sha256,
        answerSequence=view.answer_sequence,
        serverNow=view.server_now,
        items=[
            AttemptItemDTO(
                itemId=i.item_id,
                position=i.position,
                stem=i.stem,
                choices=[ChoiceDTO(**c) for c in i.choices],
                points=i.points,
                selectedKey=i.selected_key,
                answerRevision=i.answer_revision,
                clientSequence=i.client_sequence,
                savedAt=i.saved_at,
            )
            for i in view.items
        ],
    )


@router.put("/attempts/{attempt_id}/answers/{item_id}", response_model=SavedAnswerDTO)
async def save_answer(
    attempt_id: UUID, item_id: UUID, body: AnswerDTO, db: Database, claims: Claims
):
    async with student_transaction(db, claims):
        saved = await service.save_answer(
            db,
            attempt_id,
            item_id,
            selected_key=body.selectedKey,
            expected_revision=body.expectedRevision,
            client_sequence=body.clientSequence,
        )
    return SavedAnswerDTO(
        answerRevision=saved.answer_revision, savedAt=saved.saved_at, serverNow=saved.server_now
    )


@router.post("/attempts/{attempt_id}/submit", response_model=SubmissionDTO)
async def submit(
    attempt_id: UUID,
    db: Database,
    claims: Claims,
    key: IdempotencyKey = None,
):
    client_key = idempotency_key(key)
    async with student_transaction(db, claims):
        submission = await service.submit(db, attempt_id, client_key)
    await dispatch_grading(submission.job_id)
    return SubmissionDTO(
        status=submission.status,
        submittedAt=submission.submitted_at,
        snapshotSha256=submission.snapshot_sha256,
        submissionReason=submission.submission_reason,
        replayed=submission.replayed,
    )


@router.get("/attempts/{attempt_id}/results", response_model=StudentResultDTO)
async def results(attempt_id: UUID, db: Database, claims: Claims):
    async with student_transaction(db, claims):
        data = await service.results(db, attempt_id)
    return result_dto(data)
