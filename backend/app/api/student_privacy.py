"""Student self-service privacy (PILOT-05): birth year, consent status per workspace, export and
erasure of one's own data.

Birth year and consent status go through the SECURITY DEFINER functions of migration 0016 with
only the verified identity applied (students are not workspace members). Export / erasure
requests are recorded in the student's own personal workspace so the normal RLS path and the
durable job runner apply; nobody else can read them.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.identity import ApiError, Claims, Database, ErrorDTO, current_user
from app.api.jobs import dispatcher, job_dto
from app.api.privacy import (
    PrivacyRequestAcceptedDTO,
    PrivacyRequestCreateDTO,
    PrivacyRequestDTO,
    download,
    request_dto,
    request_id,
)
from app.api.workspace_access import WorkspaceScope
from app.core.audit import audit
from app.infrastructure.context import WorkspaceContext
from app.models.identity import Workspace, WorkspaceMember
from app.services import jobs as job_service
from app.services import privacy as service

router = APIRouter(
    prefix="/v1/student",
    tags=["student-privacy"],
    responses={status: {"model": ErrorDTO} for status in (401, 403, 404, 409, 422, 503)},
)

ConsentStatus = Literal["unknown", "not_required", "pending", "granted", "revoked"]


class BirthYearDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    birthYear: int = Field(ge=1900, le=2100)


class ConsentStateDTO(BaseModel):
    workspaceId: UUID
    workspaceName: str | None
    className: str | None
    birthYear: int | None
    consentStatus: ConsentStatus
    consentRequired: bool
    policyVersion: str


class ConsentStateListDTO(BaseModel):
    consentAge: int
    items: list[ConsentStateDTO]


def state_list(request: Request, states: list[service.StudentConsentState]) -> ConsentStateListDTO:
    settings = request.app.state.settings
    return ConsentStateListDTO(
        consentAge=settings.privacy_consent_age,
        items=[
            ConsentStateDTO(
                workspaceId=s.workspace_id,
                workspaceName=s.workspace_name,
                className=s.class_name,
                birthYear=s.birth_year,
                consentStatus=s.consent_status,
                consentRequired=s.consent_required,
                policyVersion=settings.privacy_policy_version,
            )
            for s in states
        ],
    )


@asynccontextmanager
async def identity_transaction(db, claims: dict) -> AsyncIterator[None]:
    try:
        async with db.begin():
            await current_user(db, claims)
            yield
    except service.PrivacyError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None


@asynccontextmanager
async def personal_transaction(db, claims: dict) -> AsyncIterator[WorkspaceScope]:
    """The caller's personal workspace (created at bootstrap) as the RLS context."""
    try:
        async with db.begin():
            user = await current_user(db, claims)
            row = (
                await db.execute(
                    select(Workspace, WorkspaceMember.role)
                    .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                    .where(
                        WorkspaceMember.user_id == user.id,
                        WorkspaceMember.status == "active",
                        Workspace.is_active.is_(True),
                        Workspace.personal_owner_user_id == user.id,
                    )
                )
            ).first()
            if row is None:
                raise ApiError(409, "onboarding_required", "Complete onboarding first.")
            workspace, role = row
            await WorkspaceContext(user.id, workspace.id).apply(db)
            yield WorkspaceScope(user=user, workspace=workspace, role=role)
    except service.PrivacyError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None


IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.put("/me/birth-year", response_model=ConsentStateListDTO)
async def set_birth_year(body: BirthYearDTO, request: Request, db: Database, claims: Claims):
    age = request.app.state.settings.privacy_consent_age
    async with identity_transaction(db, claims):
        await service.set_birth_year(db, body.birthYear, age)
        states = await service.my_consent_status(db, age)
    return state_list(request, states)


@router.get("/me/consent-status", response_model=ConsentStateListDTO)
async def consent_status(request: Request, db: Database, claims: Claims):
    age = request.app.state.settings.privacy_consent_age
    async with identity_transaction(db, claims):
        states = await service.my_consent_status(db, age)
    return state_list(request, states)


@router.post("/me/privacy-requests", response_model=PrivacyRequestAcceptedDTO, status_code=202)
async def create_privacy_request(
    body: PrivacyRequestCreateDTO,
    request: Request,
    db: Database,
    claims: Claims,
    key: IdempotencyKey = None,
):
    client_key = job_service.client_idempotency_key(key) if key is not None else None
    async with personal_transaction(db, claims) as scope:
        privacy_request, job, created = await service.request_privacy(
            db, scope, kind=body.kind, self_user_id=scope.user.id, idempotency_key=client_key
        )
        dto = PrivacyRequestAcceptedDTO(
            request=request_dto(privacy_request), job=job_dto(job) if job else None
        )
    if created:
        audit(
            "privacy.self_request_created",
            request_id=request_id(request),
            user_id=scope.user.id,
            workspace_id=scope.workspace.id,
            privacy_request_id=privacy_request.id,
            kind=body.kind,
            job_id=job.id,
        )
        await dispatcher(request)(job)
    return dto


@router.get("/me/privacy-requests/{privacy_request_id}", response_model=PrivacyRequestDTO)
async def get_privacy_request(
    privacy_request_id: UUID, request: Request, db: Database, claims: Claims
):
    async with personal_transaction(db, claims) as scope:
        privacy_request = await service.get_request(db, scope, privacy_request_id)
        if privacy_request.user_id != scope.user.id:
            raise ApiError(404, *service.REQUEST_NOT_FOUND)
    url, expires = download(request, privacy_request)
    return request_dto(privacy_request, url, expires)
