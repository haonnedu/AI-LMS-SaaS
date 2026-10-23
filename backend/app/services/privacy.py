"""Privacy: guardian consent, consent links, export and erasure requests (PILOT-05).

Legal assumptions are pending review (tasks/decisions/0008-privacy-consent-retention.md) and
every threshold comes from settings: students younger than ``privacy_consent_age`` need a
recorded consent before starting attempts; consent is recorded by school staff on paper
(``paper_school``), by a guardian through a single-use link (``guardian_link``) or by an adult
student (``self_adult``); every consent row records the notice ``policy_version``.

* Teacher functions expect ``workspace_transaction`` (RLS context) and a ``WorkspaceScope``.
  Owners/admins see every student of the workspace; teachers only students enrolled in a class
  they teach. Erasure requests need owner/admin.
* The guardian contact is normalised and hashed (sha256) before it reaches the database; the
  plaintext is never stored, logged or audited. Audit entries carry IDs only.
* Student self-service and the public guardian link go through the SECURITY DEFINER functions
  of migration 0016; student self-requests live in the student's personal workspace so the
  normal RLS path (and the durable job runner) applies.
* Export / erasure run as ``privacy.export`` / ``privacy.erase`` jobs (worker side below); both
  are idempotent on replay.
"""

import hashlib
import io
import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.models.jobs import BackgroundJob
from app.models.privacy import ConsentLink, PrivacyRequest, StudentConsent, students_privacy
from app.models.teaching import ClassTeacher, Enrollment
from app.services import classes as class_service
from app.services import jobs as job_service

ConsentStatus = Literal["unknown", "not_required", "pending", "granted", "revoked"]
ConsentMode = Literal["signup", "guardian"]
ConsentMethod = Literal["paper_school", "guardian_link", "self_adult"]
RequestKind = Literal["export", "erasure"]
RequestStatus = Literal["queued", "succeeded", "failed", "rejected"]

CONSENT_STATUSES: tuple[str, ...] = ("unknown", "not_required", "pending", "granted", "revoked")
BLOCKING_STATUSES = frozenset({"unknown", "pending", "revoked"})
STAFF_METHODS = frozenset({"paper_school", "self_adult"})
STAFF_ROLES = frozenset({"owner", "admin", "teacher"})
MANAGER_ROLES = frozenset({"owner", "admin"})
JOB_KINDS: dict[str, str] = {"export": "privacy.export", "erasure": "privacy.erase"}
REQUEST_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"succeeded", "failed", "rejected"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "rejected": frozenset(),
}
ERASED_STUDENT_NAME = "Học sinh đã xóa"
# Consent age sent to the SQL in ``signup`` mode (decision 0009, migration 0017): <= 0 means
# guardian consent is never required.
SIGNUP_GATE_AGE = 0
LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
MAX_LINK_TTL = timedelta(days=30)
DEFAULT_LINK_DAYS = 14
# Field names that must never leave the database in a privacy export.
FORBIDDEN_EXPORT_FIELDS = frozenset(
    {
        "correct_key",
        "correctKey",
        "explanation",
        "answerKey",
        "answer_key",
        "guardian_contact_hash",
        "guardianContactHash",
        "token_hash",
        "tokenHash",
    }
)

_EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,63}")
_PHONE_SEPARATORS = re.compile(r"[\s().\-]")


class Scope(Protocol):
    """Structural view of ``WorkspaceScope`` (kept here to avoid a service -> API import)."""

    user: Any
    workspace: Any
    role: str


class PrivacyError(Exception):
    status = 400

    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message


class Invalid(PrivacyError):
    status = 422


class NotFound(PrivacyError):
    status = 404


class Forbidden(PrivacyError):
    status = 403


class Conflict(PrivacyError):
    status = 409


class Gone(PrivacyError):
    status = 410


class PrivacyJobFailed(Exception):
    """Non-retryable job failure with a safe, client-visible code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class UnsafeExport(ValueError):
    """An export payload carried a field that must never leave the database."""


STUDENT_NOT_FOUND = ("student_not_found", "Không tìm thấy học sinh.")
REQUEST_NOT_FOUND = ("privacy_request_not_found", "Không tìm thấy yêu cầu dữ liệu cá nhân.")
LINK_NOT_FOUND = ("consent_link_not_found", "Liên kết xác nhận không tồn tại.")
LINK_GONE = ("consent_link_unavailable", "Liên kết xác nhận đã hết hạn hoặc đã được sử dụng.")
STUDENT_ERASED = ("student_erased", "Dữ liệu của học sinh này đã bị xóa.")


# ---- Pure helpers (unit-tested; mirrored by the SQL of migration 0016) ----------------------


def local_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(LOCAL_TZ).date()


def min_age(birth_year: int | None, today: date) -> int | None:
    """Conservative lower bound: the birthday may not have passed yet this year."""
    if birth_year is None:
        return None
    return today.year - birth_year - 1


def gate_age(mode: str, consent_age: int) -> int:
    """Consent age for the SQL gate: the configured age in ``guardian`` mode, else the
    ``signup`` sentinel 0 (consent not required)."""
    return consent_age if mode == "guardian" else SIGNUP_GATE_AGE


def consent_required(
    status: str, birth_year: int | None, consent_age: int, today: date | None = None
) -> bool:
    """Mirror of ``edu.privacy_consent_required`` (the attempt-start gate, EV017)."""
    if consent_age <= 0 or status not in BLOCKING_STATUSES:
        return False
    age = min_age(birth_year, today or local_today())
    return age is None or age < consent_age


def status_after_birth_year(
    current: str, birth_year: int, consent_age: int, today: date | None = None
) -> str:
    """Mirror of ``edu.student_set_birth_year`` (the returned status)."""
    if consent_age <= 0:
        return "not_required"
    age = min_age(birth_year, today or local_today())
    if age is not None and age >= consent_age:
        return "not_required"
    if current in {"granted", "revoked"}:
        return current
    return "pending"


def validate_birth_year(year: int, today: date | None = None) -> int:
    if not 1900 <= year <= (today or local_today()).year:
        raise Invalid("invalid_birth_year", "Năm sinh không hợp lệ.")
    return year


def normalize_contact(raw: str) -> str:
    """Email -> NFKC, trimmed, lower-case. Phone -> digits only, Vietnamese +84/84 -> 0."""
    value = unicodedata.normalize("NFKC", raw or "").strip()
    if "@" in value:
        email = value.lower()
        if len(email) > 254 or not _EMAIL.fullmatch(email):
            raise Invalid("invalid_guardian_contact", "Email hoặc số điện thoại không hợp lệ.")
        return email
    digits = _PHONE_SEPARATORS.sub("", value)
    if digits.startswith("+"):
        digits = digits[1:]
        if digits.startswith("84"):
            digits = "0" + digits[2:]
    elif digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    if not digits.isdigit() or not 9 <= len(digits) <= 15:
        raise Invalid("invalid_guardian_contact", "Email hoặc số điện thoại không hợp lệ.")
    return digits


def hash_contact(raw: str) -> bytes:
    """sha256 of the normalised contact; the plaintext is never stored."""
    return hashlib.sha256(normalize_contact(raw).encode("utf-8")).digest()


def new_link_token() -> tuple[str, bytes]:
    return class_service.new_invitation_token()


def hash_link_token(token: str) -> bytes:
    return class_service.hash_token(token)


def is_plausible_token(token: str) -> bool:
    return class_service.is_plausible_token(token)


def link_expiry(now: datetime, days: int) -> datetime:
    ttl = timedelta(days=days)
    if not timedelta(days=1) <= ttl <= MAX_LINK_TTL:
        raise ValueError("Consent link lifetime must be between 1 and 30 days")
    return now + ttl


def given_name(display_name: str) -> str:
    """Mirror of ``consent_link_info``: Vietnamese names end with the given name."""
    parts = (display_name or "").split()
    return parts[-1] if parts else ""


def can_transition(current: str, to: str) -> bool:
    return to in REQUEST_TRANSITIONS.get(current, frozenset())


def export_object_key(request: Any) -> str:
    """Server-chosen key (also enforced by ``ck_privacy_requests_object``)."""
    if request.student_id is not None:
        return f"ws/{UUID(str(request.workspace_id))}/privacy/{UUID(str(request.id))}.json"
    return f"users/{UUID(str(request.user_id))}/privacy/{UUID(str(request.id))}.json"


def assert_export_safe(payload: Any) -> None:
    """Defence in depth: refuse to write an export carrying keys/explanations/secrets."""
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            bad = FORBIDDEN_EXPORT_FIELDS.intersection(map(str, value))
            if bad:
                raise UnsafeExport(sorted(bad)[0])
            stack.extend(value.values())
        elif isinstance(value, list | tuple):
            stack.extend(value)


def summarize(statuses: Iterable[str]) -> dict[str, int]:
    counts = {"granted": 0, "pending": 0, "notRequired": 0, "revoked": 0, "unknown": 0}
    names = {"not_required": "notRequired"}
    for status in statuses:
        counts[names.get(status, status)] += 1
    return counts


def sqlstate(exc: BaseException) -> str | None:
    return getattr(getattr(exc, "orig", None), "sqlstate", None)


def _map(exc: DBAPIError, table: dict[str, PrivacyError]) -> Exception:
    mapped = table.get(sqlstate(exc) or "")
    if mapped is None:
        return exc
    return type(mapped)(mapped.code, mapped.message)


# ---- Teacher side: students, consents, links ------------------------------------------------


def _visible_students(scope: Scope):
    query = select(students_privacy).where(students_privacy.c.workspace_id == scope.workspace.id)
    if scope.role not in MANAGER_ROLES:
        query = query.where(
            exists().where(
                Enrollment.workspace_id == students_privacy.c.workspace_id,
                Enrollment.student_id == students_privacy.c.id,
                ClassTeacher.class_id == Enrollment.class_id,
                ClassTeacher.user_id == scope.user.id,
            )
        )
    return query


async def get_student(
    db: AsyncSession, scope: Scope, student_id: UUID, *, for_update: bool = False
) -> Any:
    query = _visible_students(scope).where(students_privacy.c.id == student_id)
    if for_update:
        query = query.with_for_update(of=students_privacy)
    row = (await db.execute(query)).first()
    if row is None:
        raise NotFound(*STUDENT_NOT_FOUND)
    return row


def _not_erased(student: Any) -> None:
    if student.erased_at is not None:
        raise Conflict(*STUDENT_ERASED)


async def record_consent(
    db: AsyncSession,
    scope: Scope,
    student_id: UUID,
    *,
    method: str,
    guardian_name: str | None,
    contact: str | None,
    evidence_note: str | None,
    policy_version: str,
    consent_age: int,
    today: date | None = None,
) -> StudentConsent:
    """Staff-recorded consent (paper on file, or an adult student). Sets status granted."""
    if method not in STAFF_METHODS:
        raise Invalid("invalid_consent_method", "Hình thức xác nhận không hợp lệ.")
    student = await get_student(db, scope, student_id, for_update=True)
    _not_erased(student)
    age = min_age(student.birth_year, today or local_today())
    if method == "self_adult" and age is not None and age < consent_age:
        raise Conflict("student_under_age", "Học sinh chưa đủ tuổi để tự xác nhận.")
    contact_hash = hash_contact(contact) if contact and contact.strip() else None
    consent = await db.scalar(
        insert(StudentConsent)
        .values(
            workspace_id=scope.workspace.id,
            student_id=student.id,
            method=method,
            policy_version=policy_version,
            guardian_name=(guardian_name or "").strip() or None,
            guardian_contact_hash=contact_hash,
            recorded_by_user_id=scope.user.id,
            evidence_note=(evidence_note or "").strip() or None,
        )
        .returning(StudentConsent)
    )
    audit(
        "privacy.consent_recorded",
        request_id=None,
        user_id=scope.user.id,
        workspace_id=scope.workspace.id,
        student_id=student.id,
        consent_id=consent.id,
        method=method,
    )
    return consent


async def revoke_consent(
    db: AsyncSession, scope: Scope, student_id: UUID, consent_id: UUID, reason: str
) -> StudentConsent:
    """Append-only: stamps ``revoked_at`` once; the status trigger recomputes the student."""
    student = await get_student(db, scope, student_id, for_update=True)
    consent = await db.scalar(
        select(StudentConsent)
        .where(
            StudentConsent.workspace_id == scope.workspace.id,
            StudentConsent.student_id == student.id,
            StudentConsent.id == consent_id,
        )
        .with_for_update()
    )
    if consent is None:
        raise NotFound("consent_not_found", "Không tìm thấy bản ghi đồng ý.")
    if consent.revoked_at is not None:
        return consent
    consent.revoked_at = func.clock_timestamp()
    consent.revoke_reason = reason.strip()
    await db.flush()
    await db.refresh(consent)
    audit(
        "privacy.consent_revoked",
        request_id=None,
        user_id=scope.user.id,
        workspace_id=scope.workspace.id,
        student_id=student.id,
        consent_id=consent.id,
    )
    return consent


async def create_consent_link(
    db: AsyncSession,
    scope: Scope,
    student_id: UUID,
    *,
    days: int = DEFAULT_LINK_DAYS,
    now: datetime | None = None,
) -> tuple[ConsentLink, str]:
    """Single-use guardian link; the plaintext token is returned exactly once."""
    student = await get_student(db, scope, student_id)
    _not_erased(student)
    token, digest = new_link_token()
    link = await db.scalar(
        insert(ConsentLink)
        .values(
            workspace_id=scope.workspace.id,
            student_id=student.id,
            token_hash=digest,
            expires_at=link_expiry(now or datetime.now(UTC), days),
            created_by_user_id=scope.user.id,
        )
        .returning(ConsentLink)
    )
    audit(
        "privacy.consent_link_created",
        request_id=None,
        user_id=scope.user.id,
        workspace_id=scope.workspace.id,
        student_id=student.id,
        consent_link_id=link.id,
    )
    return link, token


@dataclass(frozen=True)
class ConsentRosterEntry:
    student: Any
    consents: list[StudentConsent] = field(default_factory=list)


@dataclass(frozen=True)
class ClassConsents:
    class_id: UUID
    entries: list[ConsentRosterEntry]
    summary: dict[str, int]


async def _class_students(db: AsyncSession, scope: Scope, class_id: UUID) -> tuple[Any, list]:
    try:
        school_class = await class_service.get_class(db, scope, class_id)
    except class_service.TeachingError as exc:
        raise NotFound(exc.code, exc.message) from None
    rows = (
        await db.execute(
            select(students_privacy)
            .join(
                Enrollment,
                (Enrollment.student_id == students_privacy.c.id)
                & (Enrollment.workspace_id == students_privacy.c.workspace_id),
            )
            .where(Enrollment.class_id == school_class.id, Enrollment.status != "withdrawn")
            .order_by(students_privacy.c.display_name, students_privacy.c.id)
        )
    ).all()
    return school_class, list(rows)


async def consent_status_summary(db: AsyncSession, scope: Scope, class_id: UUID) -> dict:
    """Denominators for the roster: consent status counts of non-withdrawn students."""
    _, rows = await _class_students(db, scope, class_id)
    return summarize(row.consent_status for row in rows)


async def class_consents(db: AsyncSession, scope: Scope, class_id: UUID) -> ClassConsents:
    school_class, rows = await _class_students(db, scope, class_id)
    by_student: dict[UUID, list[StudentConsent]] = {row.id: [] for row in rows}
    if by_student:
        consents = (
            await db.scalars(
                select(StudentConsent)
                .where(
                    StudentConsent.workspace_id == scope.workspace.id,
                    StudentConsent.student_id.in_(list(by_student)),
                )
                .order_by(StudentConsent.granted_at, StudentConsent.id)
            )
        ).all()
        for consent in consents:
            by_student.setdefault(consent.student_id, []).append(consent)
    entries = [ConsentRosterEntry(row, by_student.get(row.id, [])) for row in rows]
    return ClassConsents(school_class.id, entries, summarize(r.consent_status for r in rows))


# ---- Export / erasure requests --------------------------------------------------------------


async def request_privacy(
    db: AsyncSession,
    scope: Scope,
    *,
    kind: str,
    student_id: UUID | None = None,
    self_user_id: UUID | None = None,
    idempotency_key: str | None = None,
) -> tuple[PrivacyRequest, BackgroundJob, bool]:
    """Create a privacy request and its durable job; ``(request, job, created)``.

    Teacher: ``student_id`` inside the student's workspace (erasure needs owner/admin).
    Student: ``self_user_id`` inside their personal workspace. A queued erasure for the same
    subject is returned instead of a duplicate. Must run inside the workspace transaction.
    """
    if kind not in JOB_KINDS or (student_id is None) == (self_user_id is None):
        raise Invalid("invalid_privacy_request", "Yêu cầu không hợp lệ.")
    if student_id is not None:
        if kind == "erasure" and scope.role not in MANAGER_ROLES:
            raise Forbidden("forbidden", "Chỉ quản trị viên không gian được yêu cầu xóa dữ liệu.")
        student = await get_student(db, scope, student_id, for_update=True)
        if kind == "erasure":
            _not_erased(student)
        target: dict[str, str] = {"studentId": str(student.id)}
        subject = PrivacyRequest.student_id == student.id
    else:
        target = {"userId": str(self_user_id)}
        subject = PrivacyRequest.user_id == self_user_id
    if kind == "erasure":
        pending = await db.scalar(
            select(PrivacyRequest).where(
                PrivacyRequest.workspace_id == scope.workspace.id,
                PrivacyRequest.kind == "erasure",
                PrivacyRequest.status == "queued",
                subject,
            )
        )
        if pending is not None:
            job = await db.get(BackgroundJob, pending.background_job_id)
            return pending, job, False
    job_kind = JOB_KINDS[kind]
    request_id = uuid4()
    key = idempotency_key or job_service.client_idempotency_key(None)
    job, created = await job_service.enqueue_job(
        db,
        scope,
        job_kind,
        {"privacyRequestId": str(request_id), **target},
        key,
        digest=job_service.request_hash(job_kind, target),
    )
    if not created:
        existing = await db.scalar(
            select(PrivacyRequest).where(PrivacyRequest.background_job_id == job.id)
        )
        if existing is None:
            raise Conflict(
                "idempotency_conflict", "Idempotency-Key đã được dùng cho một yêu cầu khác."
            )
        return existing, job, False
    request = await db.scalar(
        insert(PrivacyRequest)
        .values(
            id=request_id,
            workspace_id=scope.workspace.id,
            student_id=student_id,
            user_id=self_user_id,
            kind=kind,
            requested_by_user_id=scope.user.id,
            background_job_id=job.id,
        )
        .returning(PrivacyRequest)
    )
    return request, job, True


async def get_request(db: AsyncSession, scope: Scope, request_id: UUID) -> PrivacyRequest:
    request = await db.scalar(
        select(PrivacyRequest).where(
            PrivacyRequest.workspace_id == scope.workspace.id, PrivacyRequest.id == request_id
        )
    )
    if request is None:
        raise NotFound(*REQUEST_NOT_FOUND)
    if request.student_id is not None and scope.role not in MANAGER_ROLES:
        try:
            await get_student(db, scope, request.student_id)
        except NotFound:
            raise NotFound(*REQUEST_NOT_FOUND) from None
    if request.user_id is not None and request.user_id != scope.user.id:
        raise NotFound(*REQUEST_NOT_FOUND)
    return request


async def job_for(db: AsyncSession, request: PrivacyRequest) -> BackgroundJob | None:
    if request.background_job_id is None:
        return None
    return await db.get(BackgroundJob, request.background_job_id)


# ---- Student self-service (SECURITY DEFINER functions, identity only) -----------------------


STUDENT_ERRORS: dict[str, PrivacyError] = {
    "22023": Invalid("invalid_birth_year", "Năm sinh không hợp lệ."),
    "EV019": Conflict(
        "birth_year_locked", "Năm sinh đã được ghi nhận; hãy liên hệ giáo viên để sửa."
    ),
    "28000": Forbidden("account_disabled", "Tài khoản này đã bị vô hiệu hoá."),
}


@dataclass(frozen=True)
class StudentConsentState:
    workspace_id: UUID
    student_id: UUID
    consent_status: str
    consent_required: bool
    workspace_name: str | None = None
    class_name: str | None = None
    birth_year: int | None = None


async def set_birth_year(
    db: AsyncSession, year: int, consent_age: int
) -> list[StudentConsentState]:
    validate_birth_year(year)
    try:
        rows = (
            await db.execute(
                text(
                    "SELECT out_workspace_id, out_student_id, out_consent_status, "
                    "out_consent_required FROM edu.student_set_birth_year(:year, :age)"
                ),
                {"year": year, "age": consent_age},
            )
        ).all()
    except DBAPIError as exc:
        raise _map(exc, STUDENT_ERRORS) from None
    return [
        StudentConsentState(
            workspace_id=row.out_workspace_id,
            student_id=row.out_student_id,
            consent_status=row.out_consent_status,
            consent_required=bool(row.out_consent_required),
            birth_year=year,
        )
        for row in rows
    ]


async def my_consent_status(db: AsyncSession, consent_age: int) -> list[StudentConsentState]:
    try:
        rows = (
            await db.execute(
                text("SELECT * FROM edu.student_consent_status(:age)"), {"age": consent_age}
            )
        ).all()
    except DBAPIError as exc:
        raise _map(exc, STUDENT_ERRORS) from None
    return [
        StudentConsentState(
            workspace_id=row.out_workspace_id,
            student_id=row.out_student_id,
            consent_status=row.out_consent_status,
            consent_required=bool(row.out_consent_required),
            workspace_name=row.out_workspace_name,
            class_name=row.out_class_name,
            birth_year=row.out_birth_year,
        )
        for row in rows
    ]


# ---- Public guardian link (no account) ------------------------------------------------------


LINK_ERRORS: dict[str, PrivacyError] = {
    "P0002": NotFound(*LINK_NOT_FOUND),
    "EV018": Gone(*LINK_GONE),
    "22023": Invalid("invalid_consent", "Thông tin xác nhận không hợp lệ."),
}


@dataclass(frozen=True)
class LinkInfo:
    student_given_name: str
    workspace_name: str
    expires_at: datetime


@dataclass(frozen=True)
class LinkConsent:
    consent_id: UUID
    workspace_id: UUID
    student_id: UUID


async def link_info(db: AsyncSession, token: str) -> LinkInfo:
    if not is_plausible_token(token):
        raise NotFound(*LINK_NOT_FOUND)
    try:
        row = (
            await db.execute(
                text(
                    "SELECT out_student_given_name, out_workspace_name, out_expires_at "
                    "FROM edu.consent_link_info(:token_hash)"
                ),
                {"token_hash": hash_link_token(token)},
            )
        ).one()
    except DBAPIError as exc:
        raise _map(exc, LINK_ERRORS) from None
    return LinkInfo(row[0], row[1], row[2])


async def consent_by_link(
    db: AsyncSession, token: str, *, guardian_name: str, contact: str, policy_version: str
) -> LinkConsent:
    if not is_plausible_token(token):
        raise NotFound(*LINK_NOT_FOUND)
    contact_hash = hash_contact(contact)  # plaintext stops here
    try:
        row = (
            await db.execute(
                text(
                    "SELECT out_consent_id, out_workspace_id, out_student_id "
                    "FROM edu.guardian_consent_by_link(:token_hash, :name, :contact, :version)"
                ),
                {
                    "token_hash": hash_link_token(token),
                    "name": guardian_name.strip(),
                    "contact": contact_hash,
                    "version": policy_version,
                },
            )
        ).one()
    except DBAPIError as exc:
        raise _map(exc, LINK_ERRORS) from None
    return LinkConsent(row[0], row[1], row[2])


# ---- Worker side (sync session; RLS context of the job's workspace + requester) -------------


def _load_request(db: Session, job: BackgroundJob, kind: str) -> PrivacyRequest:
    try:
        request_id = UUID(str((job.input or {}).get("privacyRequestId")))
    except ValueError:
        raise PrivacyJobFailed("invalid_job_input") from None
    request = db.get(PrivacyRequest, request_id, with_for_update=True)
    if (
        request is None
        or request.workspace_id != job.workspace_id
        or request.background_job_id != job.id
        or request.kind != kind
    ):
        raise PrivacyJobFailed("invalid_job_input")
    return request


def _finish(request: PrivacyRequest, status: str, now: datetime, note: str | None = None):
    if not can_transition(request.status, status):
        return
    request.status = status
    request.finished_at = now
    if note is not None:
        request.note = note[:500]


def _replay(request: PrivacyRequest) -> dict[str, Any]:
    return {"privacyRequestId": str(request.id), "status": request.status, "replay": True}


def _definer(db: Session, sql: str, params: dict[str, Any] | None = None) -> Any:
    try:
        return db.execute(text(sql), params or {}).scalar_one()
    except DBAPIError as exc:
        if sqlstate(exc) in {"P0002", "28000"}:
            raise PrivacyJobFailed("student_not_found") from None
        raise


def run_export(ctx: Any) -> dict[str, Any]:
    """``privacy.export``: definer export -> JSON object under a server-chosen key."""
    db: Session = ctx.db
    request = _load_request(db, ctx.job, "export")
    if request.status != "queued":
        return _replay(request)
    if request.student_id is not None:
        payload = _definer(
            db, "SELECT edu.student_export(:student)", {"student": request.student_id}
        )
    else:
        payload = _definer(db, "SELECT edu.self_export()")
    try:
        assert_export_safe(payload)
    except UnsafeExport:
        raise PrivacyJobFailed("unsafe_export") from None
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    key = export_object_key(request)
    # Same key on replay: a re-put after a crash overwrites the identical object.
    ctx.store.put(
        key,
        io.BytesIO(data),
        mime="application/json",
        size=len(data),
        sha256=hashlib.sha256(data).digest(),
    )
    request.object_key = key
    _finish(request, "succeeded", ctx.clock())
    db.flush()
    audit(
        "privacy.export_completed",
        request_id=None,
        user_id=ctx.job.requested_by_user_id,
        workspace_id=request.workspace_id,
        privacy_request_id=request.id,
        student_id=request.student_id,
        size_bytes=len(data),
    )
    return {"privacyRequestId": str(request.id), "status": "succeeded", "sizeBytes": len(data)}


def purge_exports(db: Session, store: Any, workspace_id: UUID, *, student_id=None, user_id=None):
    """Delete stored export objects of one subject (S3 delete is idempotent)."""
    query = select(PrivacyRequest).where(
        PrivacyRequest.workspace_id == workspace_id,
        PrivacyRequest.kind == "export",
        PrivacyRequest.object_key.is_not(None),
    )
    if student_id is not None:
        query = query.where(PrivacyRequest.student_id == student_id)
    else:
        query = query.where(PrivacyRequest.user_id == user_id)
    purged = 0
    for request in db.scalars(query.with_for_update()):
        store.delete(request.object_key)
        request.object_key = None
        purged += 1
    db.flush()
    return purged


def run_erasure(ctx: Any) -> dict[str, Any]:
    """``privacy.erase``: purge export objects, then the definer erasure. Replays are no-ops
    (``edu.erase_student`` returns 0 for an already erased student)."""
    db: Session = ctx.db
    request = _load_request(db, ctx.job, "erasure")
    if request.status != "queued":
        return _replay(request)
    now = ctx.clock()
    if request.student_id is not None:
        purged = purge_exports(db, ctx.store, request.workspace_id, student_id=request.student_id)
        erased = _definer(db, "SELECT edu.erase_student(:student)", {"student": request.student_id})
        _finish(request, "succeeded", now)
        db.flush()
        audit(
            "privacy.student_erased",
            request_id=None,
            user_id=ctx.job.requested_by_user_id,
            workspace_id=request.workspace_id,
            privacy_request_id=request.id,
            student_id=request.student_id,
            erased=int(erased or 0),
            purged_exports=purged,
        )
        return {
            "privacyRequestId": str(request.id),
            "status": "succeeded",
            "erased": int(erased or 0),
            "purgedExports": purged,
        }
    purged = purge_exports(db, ctx.store, request.workspace_id, user_id=request.user_id)
    _finish(request, "succeeded", now)
    db.flush()
    result = {"privacyRequestId": str(request.id), "status": "succeeded", "purgedExports": purged}
    audit(
        "privacy.self_erased",
        request_id=None,
        user_id=request.user_id,
        workspace_id=request.workspace_id,
        privacy_request_id=request.id,
        purged_exports=purged,
    )
    # Complete the job BEFORE erasing: afterwards the actor is inactive, so RLS hides this
    # job row and the runner's own completion becomes a fenced no-op in the same transaction.
    job_service.complete_job(db, ctx.job.id, ctx.job.attempt, result, now)
    _definer(db, "SELECT edu.erase_self()")
    return result


def mark_failed(ctx: Any, error: Exception) -> None:
    """Permanent job failure: the request becomes ``failed`` (``rejected`` when the subject is
    no longer visible to the requester)."""
    try:
        request = _load_request(ctx.db, ctx.job, _kind_of(ctx.job))
    except PrivacyJobFailed:
        return
    code = str(getattr(error, "code", "transient_error"))[:64]
    _finish(request, "rejected" if code == "student_not_found" else "failed", ctx.clock(), code)
    ctx.db.flush()


def _kind_of(job: BackgroundJob) -> str:
    return {v: k for k, v in JOB_KINDS.items()}.get(job.kind, "")
