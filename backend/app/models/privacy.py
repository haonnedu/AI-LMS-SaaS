"""Privacy metadata (migration 0016_privacy_consent): consents, guardian links and export /
erasure requests.

The authoritative DDL, RLS policies, guard triggers and SECURITY DEFINER functions live in the
migration. ``students_privacy`` is a read/write Core view of the three columns 0016 added to
``edu.students`` on a private ``MetaData`` (the ORM ``Student`` mapping in ``teaching`` predates
them); it never creates anything.
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    MetaData,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.infrastructure.database import Base


def _id():
    return Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


def _workspace():
    return Column(UUID(as_uuid=True), ForeignKey("edu.workspaces.id"), nullable=False)


def _timestamp():
    return Column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())


def _student_fk(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["workspace_id", "student_id"],
        ["edu.students.workspace_id", "edu.students.id"],
        name=f"fk_{table}_student",
    )


class StudentConsent(Base):
    __tablename__ = "student_consents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_student_consents_workspace_id"),
        _student_fk("student_consents"),
        Index("ix_student_consents_student", "workspace_id", "student_id"),
    )
    id = _id()
    workspace_id = _workspace()
    student_id = Column(UUID(as_uuid=True), nullable=False)
    method = Column(Text, nullable=False)
    policy_version = Column(Text, nullable=False)
    guardian_name = Column(Text)
    # sha256 of the normalised email/phone; the plaintext is never stored.
    guardian_contact_hash = Column(LargeBinary)
    recorded_by_user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"))
    granted_at = _timestamp()
    revoked_at = Column(DateTime(timezone=True))
    revoke_reason = Column(Text)
    evidence_note = Column(Text)
    created_at = _timestamp()


class ConsentLink(Base):
    __tablename__ = "consent_links"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_consent_links_token_hash"),
        UniqueConstraint("workspace_id", "id", name="uq_consent_links_workspace_id"),
        _student_fk("consent_links"),
        Index("ix_consent_links_student", "workspace_id", "student_id"),
    )
    id = _id()
    workspace_id = _workspace()
    student_id = Column(UUID(as_uuid=True), nullable=False)
    token_hash = Column(LargeBinary, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True))
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"), nullable=False)
    created_at = _timestamp()


class PrivacyRequest(Base):
    __tablename__ = "privacy_requests"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_privacy_requests_workspace_id"),
        _student_fk("privacy_requests"),
        ForeignKeyConstraint(
            ["workspace_id", "background_job_id"],
            ["edu.background_jobs.workspace_id", "edu.background_jobs.id"],
            name="fk_privacy_requests_job",
        ),
        Index(
            "uq_privacy_requests_job",
            "background_job_id",
            unique=True,
            postgresql_where=text("background_job_id IS NOT NULL"),
        ),
        Index("ix_privacy_requests_student", "workspace_id", "student_id"),
    )
    id = _id()
    workspace_id = _workspace()
    student_id = Column(UUID(as_uuid=True))
    user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"))
    kind = Column(Text, nullable=False)
    status = Column(Text, nullable=False, server_default="queued")
    requested_by_user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"), nullable=False)
    background_job_id = Column(UUID(as_uuid=True))
    object_key = Column(Text)
    created_at = _timestamp()
    finished_at = Column(DateTime(timezone=True))
    note = Column(Text)


_students_metadata = MetaData(schema="edu")

# Core access to edu.students including the 0016 privacy columns (not part of Base.metadata).
students_privacy = Table(
    "students",
    _students_metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True)),
    Column("display_name", String(255), nullable=False),
    Column("status", String(20), nullable=False),
    Column("birth_year", SmallInteger),
    Column("consent_status", Text, nullable=False),
    Column("erased_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
