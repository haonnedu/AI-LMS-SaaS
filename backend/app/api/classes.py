"""Teaching portal API: classes, teachers, rosters and invitations (CLASS-01..03).

Tenant routes run inside ``workspace_transaction`` (membership + RLS context). Cross-tenant or
invisible IDs answer 404 so the API never confirms that another workspace's class exists.
Token hashes are never serialized; the invitation plaintext token is returned exactly once.
"""

import threading
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity import ApiError, Claims, Database, ErrorDTO, current_user
from app.api.workspace_access import WorkspaceScope, workspace_transaction
from app.services import classes as service
from app.services.classes import TeachingError

router = APIRouter(
    prefix="/v1",
    tags=["classes"],
    responses={status: {"model": ErrorDTO} for status in (401, 403, 404, 409, 410, 422, 429, 503)},
)

ClassStatus = Literal["active", "archived"]


# ---- DTOs -----------------------------------------------------------------------------------


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClassCreateDTO(_Input):
    name: str = Field(min_length=1, max_length=200)
    gradeLevel: str | None = Field(default=None, max_length=50)
    subject: str | None = Field(default=None, max_length=100)
    academicYear: str | None = Field(default=None, max_length=20)


class ClassDTO(BaseModel):
    id: UUID
    workspaceId: UUID
    name: str
    gradeLevel: str | None
    subject: str | None
    academicYear: str | None
    status: ClassStatus
    createdAt: datetime
    archivedAt: datetime | None


class ClassListDTO(BaseModel):
    items: list[ClassDTO]
    nextCursor: UUID | None


class TeacherAddDTO(_Input):
    userId: UUID


class ClassTeacherDTO(BaseModel):
    userId: UUID
    role: Literal["owner", "co_teacher"]


class RosterEntryDTO(BaseModel):
    enrollmentId: UUID
    studentId: UUID
    displayName: str
    status: Literal["invited", "active", "withdrawn"]
    joinedAt: datetime | None
    withdrawnAt: datetime | None


class RosterCountsDTO(BaseModel):
    enrolled: int
    invited: int
    withdrawn: int


class RosterDTO(BaseModel):
    classId: UUID
    items: list[RosterEntryDTO]
    counts: RosterCountsDTO


class InvitationCreateDTO(_Input):
    expiresInHours: int = Field(default=168, ge=1, le=720)
    maxUses: int = Field(default=1, ge=1, le=service.MAX_INVITATION_USES)


class InvitationCreatedDTO(BaseModel):
    id: UUID
    token: str
    expiresAt: datetime
    maxUses: int


class InvitationDTO(BaseModel):
    id: UUID
    classId: UUID
    expiresAt: datetime
    maxUses: int
    useCount: int
    revokedAt: datetime | None


class InvitationAcceptedDTO(BaseModel):
    classId: UUID
    className: str
    workspaceId: UUID
    enrollmentId: UUID


class EnrollmentDTO(BaseModel):
    id: UUID
    classId: UUID
    studentId: UUID
    status: Literal["invited", "active", "withdrawn"]
    joinedAt: datetime | None
    withdrawnAt: datetime | None


def class_dto(c) -> ClassDTO:
    return ClassDTO(
        id=c.id,
        workspaceId=c.workspace_id,
        name=c.name,
        gradeLevel=c.grade_level,
        subject=c.subject,
        academicYear=c.academic_year,
        status=c.status,
        createdAt=c.created_at,
        archivedAt=c.archived_at,
    )


def invitation_dto(i) -> InvitationDTO:
    return InvitationDTO(
        id=i.id,
        classId=i.class_id,
        expiresAt=i.expires_at,
        maxUses=i.max_uses,
        useCount=i.use_count,
        revokedAt=i.revoked_at,
    )


def enrollment_dto(e) -> EnrollmentDTO:
    return EnrollmentDTO(
        id=e.id,
        classId=e.class_id,
        studentId=e.student_id,
        status=e.status,
        joinedAt=e.joined_at,
        withdrawnAt=e.withdrawn_at,
    )


# ---- Rate limiting --------------------------------------------------------------------------


class TokenBucketLimiter:
    """In-process token bucket, bounded in memory (LRU eviction).

    Per-process only: with several API replicas the effective limit multiplies. Production
    needs a shared Redis-backed limiter (M7); this keeps the pilot safe on one instance.
    """

    def __init__(
        self,
        capacity: float,
        refill_per_second: float,
        *,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.capacity, self.rate, self.max_keys, self.clock = (
            capacity,
            refill_per_second,
            max_keys,
            clock,
        )
        self._buckets: OrderedDict[object, tuple[float, float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: object) -> bool:
        with self._lock:
            now = self.clock()
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            allowed = tokens >= 1
            self._buckets[key] = (tokens - 1 if allowed else tokens, now)
            self._buckets.move_to_end(key)
            while len(self._buckets) > self.max_keys:
                self._buckets.popitem(last=False)
            return allowed

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


# Every browser request reaches the API through the Next.js BFF, so the peer IP is the BFF's
# and cannot distinguish students. Limit per verified actor (subject) and per token instead:
# 5 attempts per (actor, token prefix) then one per 12 s; 200 per token then one per 2 s so a
# whole class can join with one link. Production needs a Redis-backed limiter (M7).
actor_limiter = TokenBucketLimiter(capacity=5, refill_per_second=1 / 12)
token_limiter = TokenBucketLimiter(capacity=200, refill_per_second=0.5)


def check_accept_rate(claims: dict, token: str) -> None:
    actor = f"{claims.get('iss', '')}|{claims.get('sub', '')}"
    if not (token_limiter.allow(token[:8]) and actor_limiter.allow((actor, token[:8]))):
        raise ApiError(429, "rate_limited", "Bạn thử quá nhiều lần. Vui lòng đợi rồi thử lại.")


# ---- Helpers --------------------------------------------------------------------------------


STAFF = service.STAFF_ROLES


@asynccontextmanager
async def tenant(
    db: AsyncSession, claims: dict, workspace_id: UUID
) -> AsyncIterator[WorkspaceScope]:
    try:
        async with workspace_transaction(db, claims, workspace_id, roles=STAFF) as scope:
            yield scope
    except TeachingError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None


Limit = Annotated[int, Query(ge=1, le=100)]
Token = Annotated[str, Path(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


# ---- Routes ---------------------------------------------------------------------------------


@router.post("/workspaces/{workspace_id}/classes", response_model=ClassDTO, status_code=201)
async def create_class(workspace_id: UUID, body: ClassCreateDTO, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id) as scope:
        created = await service.create_class(
            db,
            scope,
            name=body.name,
            grade_level=body.gradeLevel or None,
            subject=body.subject or None,
            academic_year=body.academicYear or None,
        )
        return class_dto(created)


@router.get("/workspaces/{workspace_id}/classes", response_model=ClassListDTO)
async def list_classes(
    workspace_id: UUID,
    db: Database,
    claims: Claims,
    cursor: UUID | None = None,
    limit: Limit = 20,
    status: ClassStatus | None = None,
):
    async with tenant(db, claims, workspace_id) as scope:
        items, next_cursor = await service.list_classes(
            db, scope, cursor=cursor, limit=limit, status=status
        )
        return ClassListDTO(items=[class_dto(c) for c in items], nextCursor=next_cursor)


@router.get("/workspaces/{workspace_id}/classes/{class_id}", response_model=ClassDTO)
async def get_class(workspace_id: UUID, class_id: UUID, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id) as scope:
        return class_dto(await service.get_class(db, scope, class_id))


@router.post("/workspaces/{workspace_id}/classes/{class_id}/archive", response_model=ClassDTO)
async def archive_class(workspace_id: UUID, class_id: UUID, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id) as scope:
        return class_dto(await service.archive_class(db, scope, class_id))


@router.get(
    "/workspaces/{workspace_id}/classes/{class_id}/teachers",
    response_model=list[ClassTeacherDTO],
)
async def list_teachers(workspace_id: UUID, class_id: UUID, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id) as scope:
        school_class = await service.get_class(db, scope, class_id)
        teachers = await service.list_teachers(db, school_class.id)
        return [ClassTeacherDTO(userId=t.user_id, role=t.role) for t in teachers]


@router.post(
    "/workspaces/{workspace_id}/classes/{class_id}/teachers",
    response_model=ClassTeacherDTO,
    status_code=201,
)
async def add_teacher(
    workspace_id: UUID, class_id: UUID, body: TeacherAddDTO, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        teacher = await service.add_co_teacher(db, scope, class_id, body.userId)
        return ClassTeacherDTO(userId=teacher.user_id, role=teacher.role)


@router.delete("/workspaces/{workspace_id}/classes/{class_id}/teachers/{user_id}", status_code=204)
async def remove_teacher(
    workspace_id: UUID, class_id: UUID, user_id: UUID, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        await service.remove_teacher(db, scope, class_id, user_id)
    return Response(status_code=204)


@router.get("/workspaces/{workspace_id}/classes/{class_id}/roster", response_model=RosterDTO)
async def roster(workspace_id: UUID, class_id: UUID, db: Database, claims: Claims):
    async with tenant(db, claims, workspace_id) as scope:
        result = await service.roster(db, scope, class_id)
        return RosterDTO(
            classId=result.school_class.id,
            items=[
                RosterEntryDTO(
                    enrollmentId=entry.enrollment.id,
                    studentId=entry.enrollment.student_id,
                    displayName=entry.display_name,
                    status=entry.enrollment.status,
                    joinedAt=entry.enrollment.joined_at,
                    withdrawnAt=entry.enrollment.withdrawn_at,
                )
                for entry in result.entries
            ],
            counts=RosterCountsDTO(**result.counts),
        )


@router.post(
    "/workspaces/{workspace_id}/classes/{class_id}/invitations",
    response_model=InvitationCreatedDTO,
    status_code=201,
)
async def create_invitation(
    workspace_id: UUID,
    class_id: UUID,
    db: Database,
    claims: Claims,
    body: InvitationCreateDTO | None = None,
):
    body = body or InvitationCreateDTO()
    async with tenant(db, claims, workspace_id) as scope:
        invitation, token = await service.create_invitation(
            db, scope, class_id, expires_in_hours=body.expiresInHours, max_uses=body.maxUses
        )
        return InvitationCreatedDTO(
            id=invitation.id,
            token=token,
            expiresAt=invitation.expires_at,
            maxUses=invitation.max_uses,
        )


@router.post(
    "/workspaces/{workspace_id}/classes/{class_id}/invitations/{invitation_id}/revoke",
    response_model=InvitationDTO,
)
async def revoke_invitation(
    workspace_id: UUID, class_id: UUID, invitation_id: UUID, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        return invitation_dto(await service.revoke_invitation(db, scope, class_id, invitation_id))


@router.post(
    "/workspaces/{workspace_id}/classes/{class_id}/enrollments/{enrollment_id}/withdraw",
    response_model=EnrollmentDTO,
)
async def withdraw_enrollment(
    workspace_id: UUID, class_id: UUID, enrollment_id: UUID, db: Database, claims: Claims
):
    async with tenant(db, claims, workspace_id) as scope:
        return enrollment_dto(await service.withdraw_enrollment(db, scope, class_id, enrollment_id))


@router.post("/invitations/{token}/accept", response_model=InvitationAcceptedDTO)
async def accept_invitation(token: Token, db: Database, claims: Claims):
    check_accept_rate(claims, token)
    try:
        async with db.begin():
            user = await current_user(db, claims)  # applies set_identity for the definer function
            accepted = await service.accept_invitation(db, token, user)
    except TeachingError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    return InvitationAcceptedDTO(
        classId=accepted.class_id,
        className=accepted.class_name,
        workspaceId=accepted.workspace_id,
        enrollmentId=accepted.enrollment_id,
    )
