"""Assessment metadata (migration 0014_assessment): assignments, attempts, answers, grading
results and append-only grade revisions.

The authoritative DDL, RLS policies, guard triggers and the student SECURITY DEFINER functions
live in the migration. Foreign keys into the exam tables (0013, ``app.models.exams``) are
deliberately not declared on these ORM classes so this module never depends on that one; the
database enforces them. ``exam_versions_ref``/``exam_items_ref`` are read-only Core tables on a
private ``MetaData`` (they are not part of ``Base.metadata`` and never create anything).
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import BIGINT, JSONB, UUID

from app.infrastructure.database import Base


def _id():
    return Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


def _workspace():
    return Column(UUID(as_uuid=True), ForeignKey("edu.workspaces.id"), nullable=False)


def _timestamp():
    return Column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_assignments_workspace_id"),
        UniqueConstraint(
            "workspace_id", "id", "exam_version_id", name="uq_assignments_version_pin"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "class_id"],
            ["edu.classes.workspace_id", "edu.classes.id"],
            name="fk_assignments_class",
        ),
        Index("ix_assignments_class", "workspace_id", "class_id", "created_at"),
    )
    id = _id()
    workspace_id = _workspace()
    class_id = Column(UUID(as_uuid=True), nullable=False)
    exam_version_id = Column(UUID(as_uuid=True), nullable=False)
    title = Column(Text, nullable=False)
    instructions = Column(Text)
    opens_at = Column(DateTime(timezone=True), nullable=False)
    closes_at = Column(DateTime(timezone=True))
    time_limit_seconds = Column(Integer)
    max_attempts = Column(Integer, nullable=False, server_default="1")
    timezone = Column(Text, nullable=False, server_default="Asia/Ho_Chi_Minh")
    status = Column(Text, nullable=False, server_default="draft")
    score_release = Column(Text, nullable=False, server_default="manual")
    solution_release = Column(Text, nullable=False, server_default="manual")
    scores_released_at = Column(DateTime(timezone=True))
    solutions_released_at = Column(DateTime(timezone=True))
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"), nullable=False)
    published_at = Column(DateTime(timezone=True))
    created_at = _timestamp()
    updated_at = _timestamp()


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_quiz_attempts_workspace_id"),
        UniqueConstraint("workspace_id", "id", "exam_version_id", name="uq_quiz_attempts_version"),
        UniqueConstraint(
            "assignment_id", "student_id", "attempt_no", name="uq_quiz_attempts_number"
        ),
        UniqueConstraint(
            "assignment_id", "student_id", "idempotency_key", name="uq_quiz_attempts_idempotency"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "assignment_id", "exam_version_id"],
            [
                "edu.assignments.workspace_id",
                "edu.assignments.id",
                "edu.assignments.exam_version_id",
            ],
            name="fk_quiz_attempts_assignment",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "student_id"],
            ["edu.students.workspace_id", "edu.students.id"],
            name="fk_quiz_attempts_student",
        ),
        Index(
            "uq_quiz_attempts_in_progress",
            "assignment_id",
            "student_id",
            unique=True,
            postgresql_where=text("status = 'in_progress'"),
        ),
    )
    id = _id()
    workspace_id = _workspace()
    assignment_id = Column(UUID(as_uuid=True), nullable=False)
    student_id = Column(UUID(as_uuid=True), nullable=False)
    exam_version_id = Column(UUID(as_uuid=True), nullable=False)
    attempt_no = Column(Integer, nullable=False)
    status = Column(Text, nullable=False, server_default="in_progress")
    started_at = _timestamp()
    deadline_at = Column(DateTime(timezone=True))
    submitted_at = Column(DateTime(timezone=True))
    submission_recorded_at = Column(DateTime(timezone=True))
    submission_reason = Column(Text)
    idempotency_key = Column(Text, nullable=False)
    request_hash = Column(Text, nullable=False)
    submit_idempotency_key = Column(Text)
    submit_request_hash = Column(Text)
    answer_sequence = Column(Integer, nullable=False, server_default="0")
    submitted_snapshot_sha256 = Column(LargeBinary)
    updated_at = _timestamp()


class StudentAnswer(Base):
    __tablename__ = "student_answers"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_student_answers_workspace_id"),
        UniqueConstraint("attempt_id", "exam_item_id", name="uq_student_answers_item"),
        ForeignKeyConstraint(
            ["workspace_id", "attempt_id", "exam_version_id"],
            [
                "edu.quiz_attempts.workspace_id",
                "edu.quiz_attempts.id",
                "edu.quiz_attempts.exam_version_id",
            ],
            name="fk_student_answers_attempt",
        ),
    )
    id = _id()
    workspace_id = _workspace()
    attempt_id = Column(UUID(as_uuid=True), nullable=False)
    exam_version_id = Column(UUID(as_uuid=True), nullable=False)
    exam_item_id = Column(UUID(as_uuid=True), nullable=False)
    response = Column(JSONB, nullable=False)
    answer_revision = Column(Integer, nullable=False, server_default="1")
    client_sequence = Column(BIGINT, nullable=False)
    saved_at = _timestamp()


class GradingResult(Base):
    __tablename__ = "grading_results"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_grading_results_workspace_id"),
        UniqueConstraint("attempt_id", "run_key", name="uq_grading_results_run"),
        UniqueConstraint("workspace_id", "attempt_id", "id", name="uq_grading_results_attempt"),
        UniqueConstraint(
            "workspace_id", "id", "exam_version_id", name="uq_grading_results_version"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "attempt_id", "exam_version_id"],
            [
                "edu.quiz_attempts.workspace_id",
                "edu.quiz_attempts.id",
                "edu.quiz_attempts.exam_version_id",
            ],
            name="fk_grading_results_attempt",
        ),
    )
    id = _id()
    workspace_id = _workspace()
    attempt_id = Column(UUID(as_uuid=True), nullable=False)
    exam_version_id = Column(UUID(as_uuid=True), nullable=False)
    run_key = Column(Text, nullable=False)
    input_hash = Column(Text, nullable=False)
    algorithm_version = Column(Text, nullable=False)
    source = Column(Text, nullable=False)
    raw_score = Column(Numeric(10, 2), nullable=False)
    max_score = Column(Numeric(10, 2), nullable=False)
    status = Column(Text, nullable=False, server_default="approved")
    supersedes_id = Column(UUID(as_uuid=True))
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"))
    created_at = _timestamp()


class GradingResultItem(Base):
    __tablename__ = "grading_result_items"
    __table_args__ = (
        UniqueConstraint("grading_result_id", "exam_item_id", name="uq_grading_result_items_item"),
        ForeignKeyConstraint(
            ["workspace_id", "grading_result_id", "exam_version_id"],
            [
                "edu.grading_results.workspace_id",
                "edu.grading_results.id",
                "edu.grading_results.exam_version_id",
            ],
            name="fk_grading_result_items_result",
        ),
    )
    # No surrogate key in the table; the (result, item) pair is the identity.
    grading_result_id = Column(UUID(as_uuid=True), primary_key=True)
    workspace_id = _workspace()
    exam_version_id = Column(UUID(as_uuid=True), nullable=False)
    exam_item_id = Column(UUID(as_uuid=True), primary_key=True)
    effective_response = Column(JSONB, nullable=False)
    answer_source = Column(Text, nullable=False)
    awarded_points = Column(Numeric(10, 2), nullable=False)
    max_points = Column(Numeric(10, 2), nullable=False)
    reason = Column(Text)


class Grade(Base):
    __tablename__ = "grades"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_grades_workspace_id"),
        UniqueConstraint("attempt_id", "revision_no", name="uq_grades_revision"),
        ForeignKeyConstraint(
            ["workspace_id", "attempt_id", "grading_result_id"],
            [
                "edu.grading_results.workspace_id",
                "edu.grading_results.attempt_id",
                "edu.grading_results.id",
            ],
            name="fk_grades_result",
        ),
        Index("uq_grades_current", "attempt_id", unique=True, postgresql_where=text("is_current")),
    )
    id = _id()
    workspace_id = _workspace()
    attempt_id = Column(UUID(as_uuid=True), nullable=False)
    grading_result_id = Column(UUID(as_uuid=True), nullable=False)
    revision_no = Column(Integer, nullable=False)
    score = Column(Numeric(10, 2), nullable=False)
    max_score = Column(Numeric(10, 2), nullable=False)
    is_current = Column(Boolean, nullable=False, server_default="true")
    approval_mode = Column(Text, nullable=False)
    approved_by_user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"))
    approved_at = _timestamp()
    released_at = Column(DateTime(timezone=True))
    reason = Column(Text)


# ---- Read-only references to the 0013 exam tables (private metadata, see module docstring) --

_exam_metadata = MetaData(schema="edu")

exam_versions_ref = Table(
    "exam_versions",
    _exam_metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("workspace_id", UUID(as_uuid=True)),
    Column("exam_id", UUID(as_uuid=True)),
    Column("version_no", Integer),
    Column("status", Text),
    Column("total_points", Numeric(10, 2)),
    Column("published_at", DateTime(timezone=True)),
)

exam_items_ref = Table(
    "exam_items",
    _exam_metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("workspace_id", UUID(as_uuid=True)),
    Column("exam_version_id", UUID(as_uuid=True)),
    Column("position", Integer),
    Column("item_type", Text),
    Column("stem", Text),
    Column("choices", JSONB),
    Column("points", Numeric(10, 2)),
)
