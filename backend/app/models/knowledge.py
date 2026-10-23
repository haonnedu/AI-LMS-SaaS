"""Curriculum metadata, immutable document versions and chunks (migration 0007_knowledge).

The authoritative DDL, RLS policies and immutability triggers live in the migration; these
mappings mirror its columns and constraint names.
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.infrastructure.database import Base

VERSION_STATUSES = ("processing", "active", "failed", "superseded")
RIGHTS_SCOPES = ("private",)


def _id():
    return Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


def _workspace():
    return Column(UUID(as_uuid=True), ForeignKey("edu.workspaces.id"), nullable=False)


def _timestamp(nullable=False):
    if nullable:
        return Column(DateTime(timezone=True))
    return Column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())


class CurriculumSubject(Base):
    """Platform-wide; runtime role has SELECT only."""

    __tablename__ = "curriculum_subjects"
    id = _id()
    code = Column(Text, nullable=False, unique=True)
    name_vi = Column(Text, nullable=False)
    created_at = _timestamp()


class CurriculumUnit(Base):
    """Platform-wide; runtime role has SELECT only. Revisions bump ``version``."""

    __tablename__ = "curriculum_units"
    __table_args__ = (
        UniqueConstraint(
            "subject_id", "grade", "program_year", "unit_code", name="uq_curriculum_units_scope"
        ),
        Index("ix_curriculum_units_listing", "subject_id", "grade", "sort_order"),
    )
    id = _id()
    subject_id = Column(
        UUID(as_uuid=True), ForeignKey("edu.curriculum_subjects.id"), nullable=False
    )
    grade = Column(SmallInteger, nullable=False)
    program_year = Column(Text, nullable=False, server_default="2018")
    unit_code = Column(Text, nullable=False)
    title_vi = Column(Text, nullable=False)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("edu.curriculum_units.id"))
    sort_order = Column(Integer, nullable=False, server_default="0")
    source_provenance = Column(Text, nullable=False)
    version = Column(Integer, nullable=False, server_default="1")
    created_at = _timestamp()


class DocumentVersion(Base):
    """Immutable once finished; at most one ``active`` per document (partial unique index)."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_document_versions_number"),
        UniqueConstraint("workspace_id", "id", name="uq_document_versions_workspace_id"),
        UniqueConstraint("workspace_id", "document_id", "id", name="uq_document_versions_owner"),
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["edu.documents.workspace_id", "edu.documents.id"],
            name="fk_document_versions_document",
        ),
        Index(
            "uq_document_versions_active",
            "document_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ix_document_versions_history",
            "workspace_id",
            "document_id",
            text("version_no DESC"),
        ),
    )
    id = _id()
    workspace_id = _workspace()
    document_id = Column(UUID(as_uuid=True), nullable=False)
    version_no = Column(Integer, nullable=False)
    status = Column(Text, nullable=False, server_default="processing")
    parser = Column(Text, nullable=False)
    parser_version = Column(Text, nullable=False)
    chunker_version = Column(Text, nullable=False)
    page_count = Column(Integer)
    char_count = Column(Integer, nullable=False, server_default="0")
    chunk_count = Column(Integer, nullable=False, server_default="0")
    text_sha256 = Column(LargeBinary)
    error_code = Column(Text)
    created_at = _timestamp()
    activated_at = _timestamp(nullable=True)


class DocumentChunk(Base):
    """Append-only (runtime has SELECT/INSERT); only insertable while the version processes."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "chunk_index", name="uq_document_chunks_index"),
        ForeignKeyConstraint(
            ["workspace_id", "document_version_id"],
            ["edu.document_versions.workspace_id", "edu.document_versions.id"],
            name="fk_document_chunks_version",
        ),
    )
    id = _id()
    workspace_id = _workspace()
    document_version_id = Column(UUID(as_uuid=True), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    page_no = Column(Integer)
    section_path = Column(Text)
    char_start = Column(Integer, nullable=False)
    char_end = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    text_sha256 = Column(LargeBinary, nullable=False)
    token_estimate = Column(Integer, nullable=False)
    created_at = _timestamp()


class DocumentCurriculumTag(Base):
    __tablename__ = "document_curriculum_tags"
    __table_args__ = (
        PrimaryKeyConstraint("document_id", "curriculum_unit_id"),
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["edu.documents.workspace_id", "edu.documents.id"],
            name="fk_document_curriculum_tags_document",
        ),
        Index("ix_document_curriculum_tags_unit", "workspace_id", "curriculum_unit_id"),
    )
    workspace_id = _workspace()
    document_id = Column(UUID(as_uuid=True), nullable=False)
    curriculum_unit_id = Column(
        UUID(as_uuid=True), ForeignKey("edu.curriculum_units.id"), nullable=False
    )
    created_at = _timestamp()
