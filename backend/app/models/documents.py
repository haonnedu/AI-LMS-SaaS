"""Private uploaded documents (migrations 0006_jobs_storage, 0007_knowledge).

Object keys are server-derived. ``rights_scope`` is private-only (no shared corpus) and
``active_version_id`` is set only by the ingest activation transaction.
"""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, LargeBinary, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.infrastructure.database import Base

DOCUMENT_STATUSES = ("pending", "uploaded", "quarantined", "deleted")


class Document(Base):
    __tablename__ = "documents"
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("edu.workspaces.id"), nullable=False)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"), nullable=False)
    file_name = Column(Text, nullable=False)
    mime_type = Column(Text, nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(LargeBinary, nullable=False)
    object_key = Column(Text, nullable=False, unique=True)
    status = Column(Text, nullable=False, server_default="pending")
    rights_attested = Column(Boolean, nullable=False, server_default="false")
    rights_scope = Column(Text, nullable=False, server_default="private")
    active_version_id = Column(UUID(as_uuid=True))
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    deleted_at = Column(DateTime(timezone=True))
