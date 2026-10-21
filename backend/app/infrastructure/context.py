"""Transaction-local verified actor and workspace context manager.

Provides session-scoped and transaction-local variables for PostgreSQL RLS
(Row Level Security) enforcement:
- edu.current_user_id: UUID of the authenticated global user.
- edu.current_workspace_id: UUID of the active tenant workspace.
"""

from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


class WorkspaceContext:
    """Encapsulates the verified actor and workspace context for a request/transaction."""

    def __init__(self, user_id: UUID | str, workspace_id: UUID | str) -> None:
        self.user_id = str(user_id)
        self.workspace_id = str(workspace_id)

    def apply(self, db: Session) -> None:
        """Set transaction-local session variables in PostgreSQL.
        
        Using LOCAL ensures settings automatically reset on transaction commit or rollback,
        preventing context leakage across connection pool reuse.
        """
        db.execute(
            text("SELECT set_config('edu.current_user_id', :user_id, true)"),
            {"user_id": self.user_id},
        )
        db.execute(
            text("SELECT set_config('edu.current_workspace_id', :workspace_id, true)"),
            {"workspace_id": self.workspace_id},
        )

    @staticmethod
    def clear(db: Session) -> None:
        """Clear context variables explicitly if needed."""
        db.execute(text("SELECT set_config('edu.current_user_id', '', true)"))
        db.execute(text("SELECT set_config('edu.current_workspace_id', '', true)"))


@contextmanager
def transaction_context(db: Session, user_id: UUID | str, workspace_id: UUID | str) -> Iterator[WorkspaceContext]:
    """Context manager to safely apply and scope actor/workspace context per transaction."""
    ctx = WorkspaceContext(user_id, workspace_id)
    ctx.apply(db)
    try:
        yield ctx
    finally:
        # Context is bound with `is_local = true` in set_config, meaning it resets
        # automatically at transaction end. We can also ensure clean state on exit.
        pass
