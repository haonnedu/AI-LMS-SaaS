"""Identity metadata shared by runtime and Alembic."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID

from app.infrastructure.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("provider_issuer", "provider_sub", name="uq_user_identity"),)
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    provider_issuer = Column(String(512), nullable=False)
    provider_sub = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    display_name = Column(String(255))
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class UserIdentity(Base):
    __tablename__ = "user_identities"
    issuer = Column(String(512), primary_key=True)
    subject = Column(String(255), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class IdentityTransfer(Base):
    __tablename__ = "identity_transfers"
    proof_id = Column(Text, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"), nullable=False)
    target_issuer = Column(Text, nullable=False)
    target_subject = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True)
    workspace_type = Column(String(50), nullable=False, server_default="personal")
    personal_owner_user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"), unique=True)
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_user"),)
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("edu.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("edu.users.id", ondelete="CASCADE"), nullable=False
    )
    role = Column(String(50), nullable=False, server_default="teacher")
    status = Column(String(50), nullable=False, server_default="active")
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
