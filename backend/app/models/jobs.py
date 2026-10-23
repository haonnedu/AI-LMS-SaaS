"""Durable job state and the lean usage ledger (migration 0006_jobs_storage)."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.infrastructure.database import Base

JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "requested_by_user_id",
            "idempotency_key",
            name="uq_background_jobs_idempotency",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_background_jobs_workspace_id"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("edu.workspaces.id"), nullable=False)
    requested_by_user_id = Column(UUID(as_uuid=True), ForeignKey("edu.users.id"), nullable=False)
    kind = Column(Text, nullable=False)
    status = Column(Text, nullable=False, server_default="queued")
    idempotency_key = Column(Text, nullable=False)
    request_hash = Column(Text, nullable=False)
    attempt = Column(Integer, nullable=False, server_default="0")
    max_attempts = Column(Integer, nullable=False, server_default="3")
    cancel_requested = Column(Boolean, nullable=False, server_default="false")
    lease_expires_at = Column(DateTime(timezone=True))
    input = Column(JSONB, nullable=False, server_default="{}")
    result = Column(JSONB)
    error_code = Column(Text)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class UsageEvent(Base):
    """Append-only: the runtime role has SELECT/INSERT only."""

    __tablename__ = "usage_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["edu.background_jobs.workspace_id", "edu.background_jobs.id"],
            name="fk_usage_events_job",
        ),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("edu.workspaces.id"), nullable=False)
    job_id = Column(UUID(as_uuid=True))
    kind = Column(Text, nullable=False)
    units = Column(Integer, nullable=False)
    unit_type = Column(Text, nullable=False)
    provider_cost_minor = Column(BigInteger)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class WorkspaceQuota(Base):
    __tablename__ = "workspace_quotas"
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("edu.workspaces.id"), primary_key=True)
    month_cap_units = Column(Integer, nullable=False, server_default="1000")
    period_start = Column(Date, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
