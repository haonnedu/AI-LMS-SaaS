"""Verified server identity in transaction-local PostgreSQL settings."""

from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_identity(db: AsyncSession, issuer: str, subject: str) -> None:
    await db.execute(
        text(
            "SELECT set_config('edu.issuer', :issuer, true), "
            "set_config('edu.subject', :subject, true)"
        ),
        {"issuer": issuer, "subject": subject},
    )


class WorkspaceContext:
    def __init__(self, user_id: UUID | str, workspace_id: UUID | str):
        self.user_id = str(UUID(str(user_id)))
        self.workspace_id = str(UUID(str(workspace_id)))

    async def apply(self, db: AsyncSession) -> None:
        await db.execute(
            text(
                "SELECT set_config('edu.current_user_id', :user_id, true), "
                "set_config('edu.current_workspace_id', :workspace_id, true)"
            ),
            {"user_id": self.user_id, "workspace_id": self.workspace_id},
        )


@asynccontextmanager
async def transaction_context(db: AsyncSession, user_id: UUID | str, workspace_id: UUID | str):
    ctx = WorkspaceContext(user_id, workspace_id)
    await ctx.apply(db)
    yield ctx
