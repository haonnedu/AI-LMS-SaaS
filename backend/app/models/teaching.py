"""Teaching metadata (classes, rosters, invitations) shared by runtime and Alembic.

The authoritative DDL, RLS policies and the invitation acceptance function live in
migration 0005_classes; these mappings mirror its columns and constraint names.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
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


class SchoolClass(Base):
    __tablename__ = "classes"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_classes_workspace_id_id"),
        CheckConstraint("status IN ('active','archived')", name="ck_classes_status"),
        Index("ix_classes_workspace_id_status", "workspace_id", "status"),
    )
    id = _id()
    workspace_id = _workspace()
    name = Column(String(200), nullable=False)
    grade_level = Column(Text)
    subject = Column(Text)
    academic_year = Column(Text)
    status = Column(String(20), nullable=False, server_default="active")
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"), nullable=False)
    archived_at = Column(DateTime(timezone=True))
    created_at = _timestamp()
    updated_at = _timestamp()


class ClassTeacher(Base):
    __tablename__ = "class_teachers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "class_id"],
            ["edu.classes.workspace_id", "edu.classes.id"],
            ondelete="CASCADE",
            name="fk_class_teachers_workspace_id_class_id_classes",
        ),
        UniqueConstraint("class_id", "user_id", name="uq_class_teachers_class_id_user_id"),
        CheckConstraint("role IN ('owner','co_teacher')", name="ck_class_teachers_role"),
    )
    id = _id()
    workspace_id = _workspace()
    class_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"), nullable=False)
    role = Column(String(20), nullable=False, server_default="co_teacher")
    created_at = _timestamp()
    updated_at = _timestamp()


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_students_workspace_id_id"),
        CheckConstraint("status IN ('active','inactive')", name="ck_students_status"),
        Index(
            "uq_students_workspace_id_user_id",
            "workspace_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_students_workspace_id_external_code",
            "workspace_id",
            "external_code",
            unique=True,
            postgresql_where=text("external_code IS NOT NULL"),
        ),
        Index("ix_students_workspace_id_status", "workspace_id", "status"),
    )
    id = _id()
    workspace_id = _workspace()
    user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"))
    display_name = Column(String(255), nullable=False)
    external_code = Column(Text)
    status = Column(String(20), nullable=False, server_default="active")
    created_at = _timestamp()
    updated_at = _timestamp()


class ClassInvitation(Base):
    __tablename__ = "class_invitations"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_class_invitations_token_hash"),
        UniqueConstraint("workspace_id", "id", name="uq_class_invitations_workspace_id_id"),
        ForeignKeyConstraint(
            ["workspace_id", "class_id"],
            ["edu.classes.workspace_id", "edu.classes.id"],
            name="fk_class_invitations_workspace_id_class_id_classes",
        ),
        CheckConstraint("max_uses BETWEEN 1 AND 500", name="ck_class_invitations_max_uses"),
        Index("ix_class_invitations_class_id", "class_id"),
    )
    id = _id()
    workspace_id = _workspace()
    class_id = Column(UUID(as_uuid=True), nullable=False)
    token_hash = Column(LargeBinary, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    max_uses = Column(Integer, nullable=False, server_default="1")
    use_count = Column(Integer, nullable=False, server_default="0")
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"), nullable=False)
    revoked_at = Column(DateTime(timezone=True))
    created_at = _timestamp()
    updated_at = _timestamp()


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_enrollments_workspace_id_id"),
        UniqueConstraint("class_id", "student_id", name="uq_enrollments_class_id_student_id"),
        ForeignKeyConstraint(
            ["workspace_id", "class_id"],
            ["edu.classes.workspace_id", "edu.classes.id"],
            name="fk_enrollments_workspace_id_class_id_classes",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "student_id"],
            ["edu.students.workspace_id", "edu.students.id"],
            name="fk_enrollments_workspace_id_student_id_students",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "invitation_id"],
            ["edu.class_invitations.workspace_id", "edu.class_invitations.id"],
            name="fk_enrollments_workspace_id_invitation_id_class_invitations",
        ),
        CheckConstraint("status IN ('invited','active','withdrawn')", name="ck_enrollments_status"),
        Index("ix_enrollments_workspace_id_status", "workspace_id", "status"),
        Index("ix_enrollments_class_id_status", "class_id", "status"),
        Index("ix_enrollments_student_id", "student_id"),
    )
    id = _id()
    workspace_id = _workspace()
    class_id = Column(UUID(as_uuid=True), nullable=False)
    student_id = Column(UUID(as_uuid=True), nullable=False)
    invitation_id = Column(UUID(as_uuid=True))
    status = Column(String(20), nullable=False, server_default="invited")
    joined_at = Column(DateTime(timezone=True))
    withdrawn_at = Column(DateTime(timezone=True))
    created_at = _timestamp()
    updated_at = _timestamp()
