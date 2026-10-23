"""AI generation provenance, exam snapshots and export jobs (0010_generation_exams).

The authoritative DDL, RLS policies, immutability triggers and the SECURITY DEFINER readers
(``edu.exam_item_key``, ``edu.exam_item_explanation``, ``edu.exam_keys_for_scoring``,
``edu.exam_version_publish_error``) live in the migration. ``ExamAnswerKey`` is INSERT-only for
the runtime role (no SELECT grant): never query it directly from application code.
"""

from sqlalchemy import (
    CHAR,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.infrastructure.database import Base

GENERATION_PURPOSES = ("lesson_plan", "study_guide", "questions")
VALIDATION_STATUSES = ("pending", "valid", "invalid", "failed")
EXAM_STATUSES = ("draft", "published", "archived")
EXPORT_FORMATS = ("docx", "pdf")
EXPORT_AUDIENCES = ("teacher", "student")
EXPORT_STATUSES = ("queued", "succeeded", "failed")


def _id():
    return Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


def _workspace():
    return Column(UUID(as_uuid=True), ForeignKey("edu.workspaces.id"), nullable=False)


def _user(nullable=False):
    return Column(UUID(as_uuid=True), ForeignKey("edu.users.id"), nullable=nullable)


def _timestamp(nullable=False):
    if nullable:
        return Column(DateTime(timezone=True))
    return Column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        UniqueConstraint("background_job_id", name="uq_generation_jobs_background_job"),
        UniqueConstraint("workspace_id", "id", name="uq_generation_jobs_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "background_job_id"],
            ["edu.background_jobs.workspace_id", "edu.background_jobs.id"],
            name="fk_generation_jobs_background_job",
        ),
        Index(
            "ix_generation_jobs_listing", "workspace_id", text("created_at DESC"), text("id DESC")
        ),
    )
    id = _id()
    workspace_id = _workspace()
    background_job_id = Column(UUID(as_uuid=True), nullable=False)
    requested_by_user_id = _user()
    purpose = Column(Text, nullable=False)
    input = Column(JSONB, nullable=False)
    prompt_version = Column(Text, nullable=False)
    provider = Column(Text, nullable=False)
    model = Column(Text, nullable=False)
    provider_request_id = Column(Text)
    output = Column(JSONB)
    validation_status = Column(Text, nullable=False, server_default="pending")
    input_tokens = Column(BigInteger)
    output_tokens = Column(BigInteger)
    cost_minor = Column(BigInteger)
    created_at = _timestamp()
    finished_at = _timestamp(nullable=True)


class GenerationSource(Base):
    """Append-only. ``chunk_id`` becomes NULL when the source chunk is purged (withdrawn)."""

    __tablename__ = "generation_sources"
    __table_args__ = (
        UniqueConstraint("generation_job_id", "rank", name="uq_generation_sources_rank"),
        UniqueConstraint("workspace_id", "id", name="uq_generation_sources_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "generation_job_id"],
            ["edu.generation_jobs.workspace_id", "edu.generation_jobs.id"],
            name="fk_generation_sources_job",
        ),
        Index("ix_generation_sources_chunk", "chunk_id"),
    )
    id = _id()
    workspace_id = _workspace()
    generation_job_id = Column(UUID(as_uuid=True), nullable=False)
    chunk_id = Column(UUID(as_uuid=True), ForeignKey("edu.document_chunks.id", ondelete="SET NULL"))
    citation_label = Column(Text, nullable=False)
    text_sha256 = Column(LargeBinary, nullable=False)
    rank = Column(Integer, nullable=False)


class Exam(Base):
    __tablename__ = "exams"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_exams_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "blueprint_version_id"],
            ["edu.blueprint_versions.workspace_id", "edu.blueprint_versions.id"],
            name="fk_exams_blueprint_version",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "id", "current_version_id"],
            [
                "edu.exam_versions.workspace_id",
                "edu.exam_versions.exam_id",
                "edu.exam_versions.id",
            ],
            name="fk_exams_current_version",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index("ix_exams_listing", "workspace_id", text("created_at DESC"), text("id DESC")),
    )
    id = _id()
    workspace_id = _workspace()
    title = Column(Text, nullable=False)
    blueprint_version_id = Column(UUID(as_uuid=True))
    status = Column(Text, nullable=False, server_default="draft")
    created_by_user_id = _user()
    current_version_id = Column(UUID(as_uuid=True))
    created_at = _timestamp()
    updated_at = _timestamp()


class ExamVersion(Base):
    """Snapshot; frozen once published (trigger), publication validated in SQL."""

    __tablename__ = "exam_versions"
    __table_args__ = (
        UniqueConstraint("exam_id", "version_no", name="uq_exam_versions_number"),
        UniqueConstraint("workspace_id", "id", name="uq_exam_versions_workspace_id"),
        UniqueConstraint("workspace_id", "exam_id", "id", name="uq_exam_versions_owner"),
        ForeignKeyConstraint(
            ["workspace_id", "exam_id"],
            ["edu.exams.workspace_id", "edu.exams.id"],
            name="fk_exam_versions_exam",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "blueprint_version_id"],
            ["edu.blueprint_versions.workspace_id", "edu.blueprint_versions.id"],
            name="fk_exam_versions_blueprint_version",
        ),
    )
    id = _id()
    workspace_id = _workspace()
    exam_id = Column(UUID(as_uuid=True), nullable=False)
    version_no = Column(Integer, nullable=False)
    status = Column(Text, nullable=False, server_default="draft")
    total_points = Column(Numeric(10, 2), nullable=False)
    content_hash = Column(LargeBinary)
    blueprint_version_id = Column(UUID(as_uuid=True))
    published_at = _timestamp(nullable=True)
    published_by_user_id = _user(nullable=True)
    created_at = _timestamp()


class ExamItem(Base):
    """Append-only snapshot of one question (runtime has SELECT/INSERT)."""

    __tablename__ = "exam_items"
    __table_args__ = (
        UniqueConstraint("exam_version_id", "position", name="uq_exam_items_position"),
        UniqueConstraint("workspace_id", "id", name="uq_exam_items_workspace_id"),
        UniqueConstraint(
            "workspace_id", "exam_version_id", "id", name="uq_exam_items_version_owner"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "exam_version_id"],
            ["edu.exam_versions.workspace_id", "edu.exam_versions.id"],
            name="fk_exam_items_version",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "source_question_revision_id"],
            ["edu.question_revisions.workspace_id", "edu.question_revisions.id"],
            name="fk_exam_items_question_revision",
        ),
    )
    id = _id()
    workspace_id = _workspace()
    exam_version_id = Column(UUID(as_uuid=True), nullable=False)
    position = Column(Integer, nullable=False)
    item_type = Column(Text, nullable=False, server_default="single_choice")
    stem = Column(Text, nullable=False)
    choices = Column(JSONB, nullable=False)
    points = Column(Numeric(10, 2), nullable=False)
    source_question_revision_id = Column(UUID(as_uuid=True))
    curriculum_unit_id = Column(UUID(as_uuid=True), ForeignKey("edu.curriculum_units.id"))
    cognitive_level = Column(Text)


class ExamAnswerKey(Base):
    """INSERT-only for the runtime role; read through ``edu.exam_item_key()`` and friends."""

    __tablename__ = "exam_answer_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "exam_version_id", "exam_item_id"],
            [
                "edu.exam_items.workspace_id",
                "edu.exam_items.exam_version_id",
                "edu.exam_items.id",
            ],
            name="fk_exam_answer_keys_item",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "exam_version_id"],
            ["edu.exam_versions.workspace_id", "edu.exam_versions.id"],
            name="fk_exam_answer_keys_version",
        ),
        Index("ix_exam_answer_keys_version", "workspace_id", "exam_version_id"),
    )
    exam_item_id = Column(UUID(as_uuid=True), primary_key=True)
    workspace_id = _workspace()
    exam_version_id = Column(UUID(as_uuid=True), nullable=False)
    correct_key = Column(CHAR(1), nullable=False)
    explanation = Column(Text)


class ExportJob(Base):
    __tablename__ = "export_jobs"
    __table_args__ = (
        UniqueConstraint("background_job_id", name="uq_export_jobs_background_job"),
        UniqueConstraint("workspace_id", "id", name="uq_export_jobs_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "background_job_id"],
            ["edu.background_jobs.workspace_id", "edu.background_jobs.id"],
            name="fk_export_jobs_background_job",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "content_revision_id"],
            ["edu.content_revisions.workspace_id", "edu.content_revisions.id"],
            name="fk_export_jobs_content_revision",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "exam_version_id"],
            ["edu.exam_versions.workspace_id", "edu.exam_versions.id"],
            name="fk_export_jobs_exam_version",
        ),
        Index("ix_export_jobs_listing", "workspace_id", text("created_at DESC"), text("id DESC")),
    )
    id = _id()
    workspace_id = _workspace()
    background_job_id = Column(UUID(as_uuid=True), nullable=False)
    content_revision_id = Column(UUID(as_uuid=True))
    exam_version_id = Column(UUID(as_uuid=True))
    format = Column(Text, nullable=False)
    audience = Column(Text, nullable=False)
    object_key = Column(Text, unique=True)
    status = Column(Text, nullable=False, server_default="queued")
    error_code = Column(Text)
    created_at = _timestamp()
    finished_at = _timestamp(nullable=True)
