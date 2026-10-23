"""Manual authoring: content revisions/review, question bank, exam blueprints (0009_authoring).

The authoritative DDL, RLS policies, immutability triggers and the teacher-only
``edu.question_key()`` function live in the migration; these mappings mirror its columns and
constraint names. ``QuestionKey`` is insert-only for the runtime role (no SELECT grant): never
query it directly from application code.
"""

from sqlalchemy import (
    CHAR,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.infrastructure.database import Base

CONTENT_KINDS = ("lesson_plan", "study_guide")
ITEM_STATUSES = ("draft", "in_review", "published", "archived")
REVISION_STATUSES = ("draft", "in_review", "approved", "published", "archived")
REVIEW_STATUSES = ("open", "changes_requested", "approved", "rejected")
ITEM_TYPES = ("single_choice",)
QUESTION_STATUSES = ("draft", "active", "retired")
COGNITIVE_LEVELS = ("remember", "understand", "apply", "analyze")
BLUEPRINT_STATUSES = ("draft", "validated", "published", "archived")
EXAM_KINDS = ("periodic", "mock")


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


class ContentItem(Base):
    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_content_items_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "id", "current_revision_id"],
            [
                "edu.content_revisions.workspace_id",
                "edu.content_revisions.content_item_id",
                "edu.content_revisions.id",
            ],
            name="fk_content_items_current_revision",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index("ix_content_items_listing", "workspace_id", text("created_at DESC"), text("id DESC")),
    )
    id = _id()
    workspace_id = _workspace()
    kind = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    created_by_user_id = _user()
    status = Column(Text, nullable=False, server_default="draft")
    current_revision_id = Column(UUID(as_uuid=True))
    latest_revision_no = Column(Integer, nullable=False, server_default="0")
    curriculum_unit_id = Column(UUID(as_uuid=True), ForeignKey("edu.curriculum_units.id"))
    created_at = _timestamp()
    updated_at = _timestamp()
    deleted_at = _timestamp(nullable=True)


class ContentRevision(Base):
    """Body editable only while ``draft``; transitions and stamps guarded by a trigger."""

    __tablename__ = "content_revisions"
    __table_args__ = (
        UniqueConstraint("content_item_id", "revision_no", name="uq_content_revisions_number"),
        UniqueConstraint("workspace_id", "id", name="uq_content_revisions_workspace_id"),
        UniqueConstraint(
            "workspace_id", "content_item_id", "id", name="uq_content_revisions_owner"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "content_item_id"],
            ["edu.content_items.workspace_id", "edu.content_items.id"],
            name="fk_content_revisions_item",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "based_on_revision_id"],
            ["edu.content_revisions.workspace_id", "edu.content_revisions.id"],
            name="fk_content_revisions_based_on",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "generation_job_id"],
            ["edu.background_jobs.workspace_id", "edu.background_jobs.id"],
            name="fk_content_revisions_generation_job",
        ),
        Index(
            "ix_content_revisions_history",
            "workspace_id",
            "content_item_id",
            text("revision_no DESC"),
        ),
    )
    id = _id()
    workspace_id = _workspace()
    content_item_id = Column(UUID(as_uuid=True), nullable=False)
    revision_no = Column(Integer, nullable=False)
    body = Column(JSONB, nullable=False)
    audience = Column(Text, nullable=False, server_default="teacher")
    status = Column(Text, nullable=False, server_default="draft")
    based_on_revision_id = Column(UUID(as_uuid=True))
    generation_job_id = Column(UUID(as_uuid=True))
    created_by_user_id = _user()
    reviewed_by_user_id = _user(nullable=True)
    reviewed_at = _timestamp(nullable=True)
    published_at = _timestamp(nullable=True)
    body_sha256 = Column(LargeBinary, nullable=False)
    created_at = _timestamp()
    updated_at = _timestamp()


class ReviewRequest(Base):
    __tablename__ = "review_requests"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_review_requests_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "content_revision_id"],
            ["edu.content_revisions.workspace_id", "edu.content_revisions.id"],
            name="fk_review_requests_revision",
        ),
        Index(
            "uq_review_requests_open",
            "content_revision_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )
    id = _id()
    workspace_id = _workspace()
    content_revision_id = Column(UUID(as_uuid=True), nullable=False)
    requested_by_user_id = _user()
    assigned_to_user_id = _user(nullable=True)
    status = Column(Text, nullable=False, server_default="open")
    comment = Column(Text)
    decided_by_user_id = _user(nullable=True)
    decided_at = _timestamp(nullable=True)
    created_at = _timestamp()


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_questions_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "id", "current_revision_id"],
            [
                "edu.question_revisions.workspace_id",
                "edu.question_revisions.question_id",
                "edu.question_revisions.id",
            ],
            name="fk_questions_current_revision",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index("ix_questions_listing", "workspace_id", text("created_at DESC"), text("id DESC")),
        Index(
            "ix_questions_filters",
            "workspace_id",
            "curriculum_unit_id",
            "cognitive_level",
            "difficulty",
        ),
        Index("ix_questions_stem_hash", "workspace_id", "stem_sha256"),
    )
    id = _id()
    workspace_id = _workspace()
    item_type = Column(Text, nullable=False, server_default="single_choice")
    stem = Column(Text, nullable=False)
    stem_sha256 = Column(LargeBinary, nullable=False)
    status = Column(Text, nullable=False, server_default="draft")
    difficulty = Column(SmallInteger)
    cognitive_level = Column(Text, nullable=False)
    curriculum_unit_id = Column(UUID(as_uuid=True), ForeignKey("edu.curriculum_units.id"))
    source_citations = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_by_user_id = _user()
    current_revision_id = Column(UUID(as_uuid=True))
    latest_revision_no = Column(Integer, nullable=False, server_default="0")
    created_at = _timestamp()
    updated_at = _timestamp()


class QuestionRevision(Base):
    """Append-only (runtime has SELECT/INSERT)."""

    __tablename__ = "question_revisions"
    __table_args__ = (
        UniqueConstraint("question_id", "revision_no", name="uq_question_revisions_number"),
        UniqueConstraint("workspace_id", "id", name="uq_question_revisions_workspace_id"),
        UniqueConstraint("workspace_id", "question_id", "id", name="uq_question_revisions_owner"),
        ForeignKeyConstraint(
            ["workspace_id", "question_id"],
            ["edu.questions.workspace_id", "edu.questions.id"],
            name="fk_question_revisions_question",
        ),
    )
    id = _id()
    workspace_id = _workspace()
    question_id = Column(UUID(as_uuid=True), nullable=False)
    revision_no = Column(Integer, nullable=False)
    stem = Column(Text, nullable=False)
    choices = Column(JSONB, nullable=False)
    explanation = Column(Text)
    created_by_user_id = _user()
    body_sha256 = Column(LargeBinary, nullable=False)
    created_at = _timestamp()


class QuestionKey(Base):
    """INSERT-only for the runtime role; read exclusively through ``edu.question_key()``."""

    __tablename__ = "question_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "question_revision_id"],
            ["edu.question_revisions.workspace_id", "edu.question_revisions.id"],
            name="fk_question_keys_revision",
        ),
    )
    question_revision_id = Column(UUID(as_uuid=True), primary_key=True)
    workspace_id = _workspace()
    correct_key = Column(CHAR(1), nullable=False)
    rationale = Column(Text)
    set_by_user_id = _user()
    created_at = _timestamp()


class QuestionObjective(Base):
    __tablename__ = "question_objectives"
    __table_args__ = (
        PrimaryKeyConstraint("question_id", "curriculum_unit_id"),
        ForeignKeyConstraint(
            ["workspace_id", "question_id"],
            ["edu.questions.workspace_id", "edu.questions.id"],
            name="fk_question_objectives_question",
        ),
        Index("ix_question_objectives_unit", "workspace_id", "curriculum_unit_id"),
    )
    workspace_id = _workspace()
    question_id = Column(UUID(as_uuid=True), nullable=False)
    curriculum_unit_id = Column(
        UUID(as_uuid=True), ForeignKey("edu.curriculum_units.id"), nullable=False
    )
    created_at = _timestamp()


class Blueprint(Base):
    __tablename__ = "blueprints"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_blueprints_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "id", "current_version_id"],
            [
                "edu.blueprint_versions.workspace_id",
                "edu.blueprint_versions.blueprint_id",
                "edu.blueprint_versions.id",
            ],
            name="fk_blueprints_current_version",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        Index("ix_blueprints_listing", "workspace_id", text("created_at DESC"), text("id DESC")),
    )
    id = _id()
    workspace_id = _workspace()
    title = Column(Text, nullable=False)
    subject_id = Column(
        UUID(as_uuid=True), ForeignKey("edu.curriculum_subjects.id"), nullable=False
    )
    grade = Column(SmallInteger, nullable=False)
    program_year = Column(Text, nullable=False, server_default="2018")
    exam_kind = Column(Text, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    total_points = Column(Numeric(6, 2), nullable=False)
    status = Column(Text, nullable=False, server_default="draft")
    current_version_id = Column(UUID(as_uuid=True))
    latest_version_no = Column(Integer, nullable=False, server_default="0")
    effective_year = Column(SmallInteger, nullable=False)
    origin_kind = Column(Text, nullable=False, server_default="teacher_defined")
    provenance = Column(Text, nullable=False)
    created_by_user_id = _user()
    created_at = _timestamp()
    updated_at = _timestamp()


class BlueprintVersion(Base):
    """Body immutable from creation; frozen entirely once published (trigger)."""

    __tablename__ = "blueprint_versions"
    __table_args__ = (
        UniqueConstraint("blueprint_id", "version_no", name="uq_blueprint_versions_number"),
        UniqueConstraint("workspace_id", "id", name="uq_blueprint_versions_workspace_id"),
        UniqueConstraint("workspace_id", "blueprint_id", "id", name="uq_blueprint_versions_owner"),
        ForeignKeyConstraint(
            ["workspace_id", "blueprint_id"],
            ["edu.blueprints.workspace_id", "edu.blueprints.id"],
            name="fk_blueprint_versions_blueprint",
        ),
    )
    id = _id()
    workspace_id = _workspace()
    blueprint_id = Column(UUID(as_uuid=True), nullable=False)
    version_no = Column(Integer, nullable=False)
    body = Column(JSONB, nullable=False)
    status = Column(Text, nullable=False, server_default="draft")
    validation_report = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    body_sha256 = Column(LargeBinary, nullable=False)
    created_by_user_id = _user()
    published_by_user_id = _user(nullable=True)
    created_at = _timestamp()
    validated_at = _timestamp(nullable=True)
    published_at = _timestamp(nullable=True)
