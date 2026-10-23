"""Classes, rosters and invitations (CLASS-01..03).

Every function except ``accept_invitation`` expects the caller to have opened
``app.api.workspace_access.workspace_transaction`` and passes its ``WorkspaceScope``. RLS
already confines rows to that workspace; these functions add class-scoped authorization:
workspace owners/admins manage every class, teachers see only classes they teach.

Invitation tokens are bearer secrets for *joining* only, never for reading content. The
plaintext is returned once; only its sha256 digest is stored.
"""

import hashlib
import re
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import exists, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.teaching import ClassInvitation, ClassTeacher, Enrollment, SchoolClass, Student

STAFF_ROLES = frozenset({"owner", "admin", "teacher"})
MANAGER_ROLES = frozenset({"owner", "admin"})
MAX_INVITATION_TTL = timedelta(days=30)
MIN_INVITATION_TTL = timedelta(hours=1)
MAX_INVITATION_USES = 500
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}")


class Scope(Protocol):
    """Structural view of ``WorkspaceScope`` (kept here to avoid a service -> API import)."""

    user: Any
    workspace: Any
    role: str


class TeachingError(Exception):
    status = 400

    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message


class NotFound(TeachingError):
    status = 404


class Forbidden(TeachingError):
    status = 403


class Conflict(TeachingError):
    status = 409


class Gone(TeachingError):
    status = 410


CLASS_NOT_FOUND = ("class_not_found", "Không tìm thấy lớp học.")


# ---- Pure helpers (unit-tested; mirrored by edu.accept_class_invitation) --------------------


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def new_invitation_token() -> tuple[str, bytes]:
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def is_plausible_token(token: str) -> bool:
    return bool(TOKEN_PATTERN.fullmatch(token))


def invitation_expiry(now: datetime, hours: int) -> datetime:
    ttl = timedelta(hours=hours)
    if not MIN_INVITATION_TTL <= ttl <= MAX_INVITATION_TTL:
        raise ValueError("Invitation lifetime must be between 1 hour and 30 days")
    return now + ttl


def validate_max_uses(max_uses: int) -> int:
    if not 1 <= max_uses <= MAX_INVITATION_USES:
        raise ValueError("max_uses must be between 1 and 500")
    return max_uses


def invitation_unavailable_reason(
    *,
    revoked_at: datetime | None,
    expires_at: datetime,
    use_count: int,
    max_uses: int,
    now: datetime,
) -> str | None:
    """Same order of checks as the SQL function (revoked, expired, exhausted)."""
    if revoked_at is not None:
        return "revoked"
    if expires_at <= now:
        return "expired"
    if use_count >= max_uses:
        return "exhausted"
    return None


def page(rows: Sequence[Any], limit: int, key: Callable[[Any], UUID]) -> tuple[list, UUID | None]:
    """Keyset page from ``limit + 1`` ordered rows: next cursor is the last returned key."""
    items = list(rows[:limit])
    return items, key(items[-1]) if len(rows) > limit else None


# ---- Class lookup and authorization ---------------------------------------------------------


def _teaches(scope: Scope, class_column=SchoolClass.id):
    return exists().where(
        ClassTeacher.class_id == class_column,
        ClassTeacher.user_id == scope.user.id,
    )


def visible_classes(scope: Scope):
    query = select(SchoolClass).where(SchoolClass.workspace_id == scope.workspace.id)
    if scope.role not in MANAGER_ROLES:
        query = query.where(_teaches(scope))
    return query


async def get_class(
    db: AsyncSession, scope: Scope, class_id: UUID, *, for_update: bool = False
) -> SchoolClass:
    query = visible_classes(scope).where(SchoolClass.id == class_id)
    if for_update:
        query = query.with_for_update()
    found = await db.scalar(query)
    if found is None:
        raise NotFound(*CLASS_NOT_FOUND)
    return found


async def _require_manager(db: AsyncSession, scope: Scope, school_class: SchoolClass) -> None:
    if scope.role in MANAGER_ROLES:
        return
    role = await db.scalar(
        select(ClassTeacher.role).where(
            ClassTeacher.class_id == school_class.id, ClassTeacher.user_id == scope.user.id
        )
    )
    if role != "owner":
        raise Forbidden("forbidden", "Chỉ giáo viên chủ nhiệm lớp được thực hiện thao tác này.")


def _require_active(school_class: SchoolClass) -> None:
    if school_class.status != "active":
        raise Conflict("class_archived", "Lớp học đã được lưu trữ.")


# ---- Classes --------------------------------------------------------------------------------


async def create_class(
    db: AsyncSession,
    scope: Scope,
    *,
    name: str,
    grade_level: str | None = None,
    subject: str | None = None,
    academic_year: str | None = None,
) -> SchoolClass:
    school_class = await db.scalar(
        insert(SchoolClass)
        .values(
            workspace_id=scope.workspace.id,
            name=name,
            grade_level=grade_level,
            subject=subject,
            academic_year=academic_year,
            created_by_user_id=scope.user.id,
        )
        .returning(SchoolClass)
    )
    await db.execute(
        insert(ClassTeacher).values(
            workspace_id=scope.workspace.id,
            class_id=school_class.id,
            user_id=scope.user.id,
            role="owner",
        )
    )
    return school_class


async def list_classes(
    db: AsyncSession,
    scope: Scope,
    *,
    cursor: UUID | None,
    limit: int,
    status: str | None = None,
) -> tuple[list[SchoolClass], UUID | None]:
    query = visible_classes(scope).order_by(SchoolClass.id).limit(limit + 1)
    if cursor:
        query = query.where(SchoolClass.id > cursor)
    if status:
        query = query.where(SchoolClass.status == status)
    rows = (await db.scalars(query)).all()
    return page(rows, limit, lambda row: row.id)


async def archive_class(db: AsyncSession, scope: Scope, class_id: UUID) -> SchoolClass:
    school_class = await get_class(db, scope, class_id, for_update=True)
    await _require_manager(db, scope, school_class)
    if school_class.status == "archived":
        return school_class
    school_class.status = "archived"
    school_class.archived_at = func.clock_timestamp()
    school_class.updated_at = func.clock_timestamp()
    await db.flush()
    # Outstanding join links stop working immediately; enrollments keep their history.
    await db.execute(
        update(ClassInvitation)
        .where(ClassInvitation.class_id == school_class.id, ClassInvitation.revoked_at.is_(None))
        .values(revoked_at=func.clock_timestamp(), updated_at=func.clock_timestamp())
        .execution_options(synchronize_session=False)
    )
    await db.refresh(school_class)
    return school_class


# ---- Teachers -------------------------------------------------------------------------------


async def add_co_teacher(
    db: AsyncSession, scope: Scope, class_id: UUID, user_id: UUID
) -> ClassTeacher:
    school_class = await get_class(db, scope, class_id, for_update=True)
    await _require_manager(db, scope, school_class)
    _require_active(school_class)
    role = await db.scalar(
        text("SELECT edu.workspace_staff_role(:workspace, :user)"),
        {"workspace": scope.workspace.id, "user": user_id},
    )
    if role is None:
        # Same answer for unknown users and non-members: do not confirm account existence.
        raise NotFound("member_not_found", "Không tìm thấy giáo viên trong không gian này.")
    await db.execute(
        pg_insert(ClassTeacher)
        .values(
            workspace_id=scope.workspace.id,
            class_id=school_class.id,
            user_id=user_id,
            role="co_teacher",
        )
        .on_conflict_do_nothing(index_elements=["class_id", "user_id"])
    )
    return await db.scalar(
        select(ClassTeacher).where(
            ClassTeacher.class_id == school_class.id, ClassTeacher.user_id == user_id
        )
    )


async def remove_teacher(db: AsyncSession, scope: Scope, class_id: UUID, user_id: UUID) -> None:
    school_class = await get_class(db, scope, class_id, for_update=True)
    await _require_manager(db, scope, school_class)
    teacher = await db.scalar(
        select(ClassTeacher).where(
            ClassTeacher.class_id == school_class.id, ClassTeacher.user_id == user_id
        )
    )
    if teacher is None:
        raise NotFound("teacher_not_found", "Giáo viên không thuộc lớp này.")
    if teacher.role == "owner":
        raise Conflict("class_owner_required", "Không thể gỡ giáo viên chủ nhiệm khỏi lớp.")
    await db.delete(teacher)
    await db.flush()


async def list_teachers(db: AsyncSession, class_id: UUID) -> list[ClassTeacher]:
    query = select(ClassTeacher).where(ClassTeacher.class_id == class_id)
    return list((await db.scalars(query.order_by(ClassTeacher.created_at))).all())


# ---- Roster ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class RosterEntry:
    enrollment: Enrollment
    display_name: str


@dataclass(frozen=True)
class Roster:
    school_class: SchoolClass
    entries: list[RosterEntry]
    counts: dict[str, int]


def roster_counts(statuses: Sequence[str]) -> dict[str, int]:
    counts = {"enrolled": 0, "invited": 0, "withdrawn": 0}
    names = {"active": "enrolled", "invited": "invited", "withdrawn": "withdrawn"}
    for status in statuses:
        counts[names[status]] += 1
    return counts


async def roster(db: AsyncSession, scope: Scope, class_id: UUID) -> Roster:
    school_class = await get_class(db, scope, class_id)
    rows = (
        await db.execute(
            select(Enrollment, Student.display_name)
            .join(
                Student,
                (Student.id == Enrollment.student_id)
                & (Student.workspace_id == Enrollment.workspace_id),
            )
            .where(Enrollment.class_id == school_class.id)
            .order_by(Student.display_name, Enrollment.id)
        )
    ).all()
    entries = [RosterEntry(enrollment, name) for enrollment, name in rows]
    return Roster(school_class, entries, roster_counts([e.enrollment.status for e in entries]))


async def withdraw_enrollment(
    db: AsyncSession, scope: Scope, class_id: UUID, enrollment_id: UUID
) -> Enrollment:
    school_class = await get_class(db, scope, class_id)
    enrollment = await db.scalar(
        select(Enrollment)
        .where(Enrollment.id == enrollment_id, Enrollment.class_id == school_class.id)
        .with_for_update()
    )
    if enrollment is None:
        raise NotFound("enrollment_not_found", "Không tìm thấy học sinh trong lớp.")
    if enrollment.status == "withdrawn":
        return enrollment
    enrollment.status = "withdrawn"
    enrollment.withdrawn_at = func.clock_timestamp()
    enrollment.updated_at = func.clock_timestamp()
    await db.flush()
    await db.refresh(enrollment)
    return enrollment


# ---- Invitations ----------------------------------------------------------------------------


async def create_invitation(
    db: AsyncSession,
    scope: Scope,
    class_id: UUID,
    *,
    expires_in_hours: int,
    max_uses: int,
    now: datetime | None = None,
) -> tuple[ClassInvitation, str]:
    school_class = await get_class(db, scope, class_id)
    _require_active(school_class)
    expires_at = invitation_expiry(now or datetime.now(UTC), expires_in_hours)
    token, digest = new_invitation_token()
    invitation = await db.scalar(
        insert(ClassInvitation)
        .values(
            workspace_id=scope.workspace.id,
            class_id=school_class.id,
            token_hash=digest,
            expires_at=expires_at,
            max_uses=validate_max_uses(max_uses),
            created_by_user_id=scope.user.id,
        )
        .returning(ClassInvitation)
    )
    return invitation, token


async def revoke_invitation(
    db: AsyncSession, scope: Scope, class_id: UUID, invitation_id: UUID
) -> ClassInvitation:
    school_class = await get_class(db, scope, class_id)
    invitation = await db.scalar(
        select(ClassInvitation)
        .where(ClassInvitation.id == invitation_id, ClassInvitation.class_id == school_class.id)
        .with_for_update()
    )
    if invitation is None:
        raise NotFound("invitation_not_found", "Không tìm thấy lời mời.")
    if invitation.revoked_at is not None:
        return invitation
    invitation.revoked_at = func.clock_timestamp()
    invitation.updated_at = func.clock_timestamp()
    await db.flush()
    await db.refresh(invitation)
    return invitation


@dataclass(frozen=True)
class AcceptedInvitation:
    enrollment_id: UUID
    class_id: UUID
    class_name: str
    workspace_id: UUID


INVITATION_ERRORS: dict[str, TeachingError] = {
    "P0002": NotFound("invitation_not_found", "Lời mời không tồn tại."),
    "EV001": Gone("invitation_unavailable", "Lời mời đã hết hạn, bị thu hồi hoặc đã dùng hết."),
    "EV002": Conflict("enrollment_withdrawn", "Bạn không thể tham gia lại lớp bằng lời mời này."),
    "28000": Forbidden("account_disabled", "Tài khoản này đã bị vô hiệu hoá."),
}


async def accept_invitation(db: AsyncSession, token: str, actor_user: Any) -> AcceptedInvitation:
    """Run inside a transaction whose verified identity (``set_identity``) is ``actor_user``.

    The definer function locks the invitation row (FOR UPDATE), so two concurrent accepts of
    a single-use token serialize and exactly one succeeds.
    """
    if not is_plausible_token(token):
        raise INVITATION_ERRORS["P0002"]
    try:
        row = (
            await db.execute(
                text(
                    "SELECT out_enrollment_id, out_class_id, out_class_name, out_workspace_id "
                    "FROM edu.accept_class_invitation(:token_hash)"
                ),
                {"token_hash": hash_token(token)},
            )
        ).one()
    except DBAPIError as exc:
        mapped = INVITATION_ERRORS.get(getattr(exc.orig, "sqlstate", None) or "")
        if mapped is None:
            raise
        raise type(mapped)(mapped.code, mapped.message) from None
    return AcceptedInvitation(
        enrollment_id=row[0], class_id=row[1], class_name=row[2], workspace_id=row[3]
    )
