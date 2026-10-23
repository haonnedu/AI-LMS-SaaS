"""Teacher privacy API (PILOT-05): class consent roster, staff-recorded consents, guardian
links, export and erasure requests.

Every route runs inside ``workspace_transaction`` (membership + RLS context); cross-workspace
or invisible IDs answer 404. The guardian contact is hashed in the service and never echoed;
consent link tokens are returned exactly once. Audit lines carry IDs only.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity import ApiError, Claims, Database, ErrorDTO
from app.api.jobs import JobDTO, dispatcher, job_dto
from app.api.workspace_access import WorkspaceScope, workspace_transaction
from app.core.audit import audit
from app.services import jobs as job_service
from app.services import privacy as service
from app.services.storage import ObjectStore

router = APIRouter(
    prefix="/v1",
    tags=["privacy"],
    responses={status: {"model": ErrorDTO} for status in (401, 403, 404, 409, 422, 503)},
)

ConsentStatus = Literal["unknown", "not_required", "pending", "granted", "revoked"]
ConsentMethod = Literal["paper_school", "guardian_link", "self_adult"]
RequestKind = Literal["export", "erasure"]
RequestStatus = Literal["queued", "succeeded", "failed", "rejected"]


# ---- DTOs -----------------------------------------------------------------------------------


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConsentDTO(BaseModel):
    id: UUID
    method: ConsentMethod
    policyVersion: str
    grantedAt: datetime
    revokedAt: datetime | None


class ConsentRosterEntryDTO(BaseModel):
    studentId: UUID
    displayName: str
    birthYear: int | None
    consentStatus: ConsentStatus
    consentRequired: bool
    consents: list[ConsentDTO]


class ConsentSummaryDTO(BaseModel):
    granted: int
    pending: int
    notRequired: int
    revoked: int
    unknown: int


class ClassConsentsDTO(BaseModel):
    classId: UUID
    consentAge: int
    mode: Literal["signup", "guardian"]
    policyVersion: str
    items: list[ConsentRosterEntryDTO]
    summary: ConsentSummaryDTO


class ConsentCreateDTO(_Input):
    method: Literal["paper_school", "self_adult"]
    guardianName: str | None = Field(default=None, max_length=200)
    guardianContact: str | None = Field(default=None, max_length=254)
    evidenceNote: str | None = Field(default=None, max_length=500)


class ConsentRevokeDTO(_Input):
    reason: str = Field(min_length=1, max_length=500)


class ConsentLinkCreateDTO(_Input):
    expiresInDays: int = Field(default=service.DEFAULT_LINK_DAYS, ge=1, le=30)


class ConsentLinkCreatedDTO(BaseModel):
    id: UUID
    token: str
    expiresAt: datetime


class PrivacyRequestCreateDTO(_Input):
    kind: RequestKind


class PrivacyRequestDTO(BaseModel):
    id: UUID
    workspaceId: UUID
    kind: RequestKind
    status: RequestStatus
    studentId: UUID | None
    userId: UUID | None
    jobId: UUID | None
    createdAt: datetime
    finishedAt: datetime | None
    note: str | None
    downloadUrl: str | None = None
    downloadExpiresAt: datetime | None = None


class PrivacyRequestAcceptedDTO(BaseModel):
    request: PrivacyRequestDTO
    job: JobDTO | None


def consent_dto(c) -> ConsentDTO:
    return ConsentDTO(
        id=c.id,
        method=c.method,
        policyVersion=c.policy_version,
        grantedAt=c.granted_at,
        revokedAt=c.revoked_at,
    )


def request_dto(r, url: str | None = None, expires: datetime | None = None) -> PrivacyRequestDTO:
    return PrivacyRequestDTO(
        id=r.id,
        workspaceId=r.workspace_id,
        kind=r.kind,
        status=r.status,
        studentId=r.student_id,
        userId=r.user_id,
        jobId=r.background_job_id,
        createdAt=r.created_at,
        finishedAt=r.finished_at,
        note=r.note,
        downloadUrl=url,
        downloadExpiresAt=expires if url else None,
    )


# ---- Helpers --------------------------------------------------------------------------------


STAFF = service.STAFF_ROLES


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or ""


def object_store(request: Request) -> ObjectStore:
    store = getattr(request.app.state, "object_store", None)
    if store is None:
        store = ObjectStore(request.app.state.settings)
        request.app.state.object_store = store
    return store


def download(request: Request, privacy_request) -> tuple[str | None, datetime | None]:
    """Short-lived signed URL for a finished export (never logged)."""
    if (
        privacy_request.kind != "export"
        or privacy_request.status != "succeeded"
        or not privacy_request.object_key
    ):
        return None, None
    return object_store(request).presign_get(
        privacy_request.object_key,
        file_name=f"eduvia-du-lieu-ca-nhan-{privacy_request.id}.json",
        mime="application/json",
        ttl_seconds=request.app.state.settings.privacy_export_url_seconds,
    )


@asynccontextmanager
async def tenant(
    db: AsyncSession, claims: dict, workspace_id: UUID
) -> AsyncIterator[WorkspaceScope]:
    try:
        async with workspace_transaction(db, claims, workspace_id, roles=STAFF) as scope:
            yield scope
    except service.PrivacyError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None


IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


async def create_request(
    request: Request,
    db: AsyncSession,
    claims: dict,
    workspace_id: UUID,
    student_id: UUID,
    kind: str,
    key: str | None,
) -> PrivacyRequestAcceptedDTO:
    client_key = job_service.client_idempotency_key(key) if key is not None else None
    async with tenant(db, claims, workspace_id) as scope:
        privacy_request, job, created = await service.request_privacy(
            db, scope, kind=kind, student_id=student_id, idempotency_key=client_key
        )
        dto = PrivacyRequestAcceptedDTO(
            request=request_dto(privacy_request), job=job_dto(job) if job else None
        )
    if created:
        audit(
            "privacy.request_created",
            request_id=request_id(request),
            user_id=scope.user.id,
            workspace_id=workspace_id,
            privacy_request_id=privacy_request.id,
            student_id=student_id,
            kind=kind,
            job_id=job.id,
        )
        await dispatcher(request)(job)
    return dto


# ---- Routes ---------------------------------------------------------------------------------


@router.get(
    "/workspaces/{workspace_id}/classes/{class_id}/consents", response_model=ClassConsentsDTO
)
async def class_consents(
    workspace_id: UUID, class_id: UUID, request: Request, db: Database, claims: Claims
):
    settings = request.app.state.settings
    age = settings.privacy_consent_age
    gate = service.gate_age(settings.privacy_consent_mode, age)
    async with tenant(db, claims, workspace_id) as scope:
        result = await service.class_consents(db, scope, class_id)
        today = service.local_today()
        return ClassConsentsDTO(
            classId=result.class_id,
            consentAge=age,
            mode=settings.privacy_consent_mode,
            policyVersion=settings.privacy_policy_version,
            items=[
                ConsentRosterEntryDTO(
                    studentId=entry.student.id,
                    displayName=entry.student.display_name,
                    birthYear=entry.student.birth_year,
                    consentStatus=entry.student.consent_status,
                    consentRequired=service.consent_required(
                        entry.student.consent_status, entry.student.birth_year, gate, today
                    ),
                    consents=[consent_dto(c) for c in entry.consents],
                )
                for entry in result.entries
            ],
            summary=ConsentSummaryDTO(**result.summary),
        )


@router.post(
    "/workspaces/{workspace_id}/students/{student_id}/consents",
    response_model=ConsentDTO,
    status_code=201,
)
async def record_consent(
    workspace_id: UUID,
    student_id: UUID,
    body: ConsentCreateDTO,
    request: Request,
    db: Database,
    claims: Claims,
):
    settings = request.app.state.settings
    async with tenant(db, claims, workspace_id) as scope:
        consent = await service.record_consent(
            db,
            scope,
            student_id,
            method=body.method,
            guardian_name=body.guardianName,
            contact=body.guardianContact,
            evidence_note=body.evidenceNote,
            policy_version=settings.privacy_policy_version,
            consent_age=settings.privacy_consent_age,
        )
        return consent_dto(consent)


@router.post(
    "/workspaces/{workspace_id}/students/{student_id}/consents/{consent_id}/revoke",
    response_model=ConsentDTO,
)
async def revoke_consent(
    workspace_id: UUID,
    student_id: UUID,
    consent_id: UUID,
    body: ConsentRevokeDTO,
    db: Database,
    claims: Claims,
):
    async with tenant(db, claims, workspace_id) as scope:
        consent = await service.revoke_consent(db, scope, student_id, consent_id, body.reason)
        return consent_dto(consent)


@router.post(
    "/workspaces/{workspace_id}/students/{student_id}/consent-links",
    response_model=ConsentLinkCreatedDTO,
    status_code=201,
)
async def create_consent_link(
    workspace_id: UUID,
    student_id: UUID,
    db: Database,
    claims: Claims,
    body: ConsentLinkCreateDTO | None = None,
):
    body = body or ConsentLinkCreateDTO()
    async with tenant(db, claims, workspace_id) as scope:
        link, token = await service.create_consent_link(
            db, scope, student_id, days=body.expiresInDays
        )
        return ConsentLinkCreatedDTO(id=link.id, token=token, expiresAt=link.expires_at)


@router.post(
    "/workspaces/{workspace_id}/students/{student_id}/privacy-requests",
    response_model=PrivacyRequestAcceptedDTO,
    status_code=202,
)
async def create_privacy_request(
    workspace_id: UUID,
    student_id: UUID,
    body: PrivacyRequestCreateDTO,
    request: Request,
    db: Database,
    claims: Claims,
    key: IdempotencyKey = None,
):
    return await create_request(request, db, claims, workspace_id, student_id, body.kind, key)


@router.post(
    "/workspaces/{workspace_id}/students/{student_id}/erase",
    response_model=PrivacyRequestAcceptedDTO,
    status_code=202,
)
async def erase_student(
    workspace_id: UUID,
    student_id: UUID,
    request: Request,
    db: Database,
    claims: Claims,
    key: IdempotencyKey = None,
):
    return await create_request(request, db, claims, workspace_id, student_id, "erasure", key)


@router.get(
    "/workspaces/{workspace_id}/privacy-requests/{privacy_request_id}",
    response_model=PrivacyRequestDTO,
)
async def get_privacy_request(
    workspace_id: UUID,
    privacy_request_id: UUID,
    request: Request,
    db: Database,
    claims: Claims,
):
    async with tenant(db, claims, workspace_id) as scope:
        privacy_request = await service.get_request(db, scope, privacy_request_id)
    url, expires = download(request, privacy_request)
    return request_dto(privacy_request, url, expires)
