"""Shared workspace authorization for tenant routes (BE-05).

Every tenant endpoint must run its database work inside ``workspace_transaction``:
it verifies the caller's active membership in the requested workspace and binds the
transaction-local RLS context before any tenant table is touched. Client-selected
workspace IDs are never trusted without this check.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity import ApiError, accessible_workspaces, current_user
from app.infrastructure.context import WorkspaceContext
from app.models.identity import User, Workspace


@dataclass(frozen=True)
class WorkspaceScope:
    user: User
    workspace: Workspace
    role: str


@asynccontextmanager
async def workspace_transaction(
    db: AsyncSession,
    claims: dict[str, Any],
    workspace_id: UUID,
    *,
    roles: frozenset[str] | None = None,
) -> AsyncIterator[WorkspaceScope]:
    """Open one transaction with verified actor + workspace RLS context applied.

    Raises 404 (not 403) for unknown or inaccessible workspaces so the API does not
    reveal whether a workspace ID exists. ``roles`` optionally restricts the membership
    roles allowed to perform the operation (e.g. ``frozenset({"owner", "teacher"})``).
    """
    async with db.begin():
        user = await current_user(db, claims)
        row = (
            await db.execute(accessible_workspaces(user).where(Workspace.id == workspace_id))
        ).first()
        if row is None:
            raise ApiError(404, "workspace_not_found", "Workspace not found.")
        workspace, role = row
        if roles is not None and role not in roles:
            raise ApiError(403, "forbidden", "You cannot perform this action here.")
        await WorkspaceContext(user.id, workspace.id).apply(db)
        yield WorkspaceScope(user=user, workspace=workspace, role=role)
