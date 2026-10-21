"""Tests for transaction-local actor and workspace context (DB-03)."""

from uuid import uuid4
import pytest
from sqlalchemy import text
from app.infrastructure.context import WorkspaceContext, transaction_context


def test_workspace_context_unit():
    user_id = uuid4()
    workspace_id = uuid4()
    ctx = WorkspaceContext(user_id, workspace_id)
    assert ctx.user_id == str(user_id)
    assert ctx.workspace_id == str(workspace_id)


def test_transaction_context_manager():
    user_id = uuid4()
    workspace_id = uuid4()
    
    # Mock session object to test execute calls
    class MockSession:
        def __init__(self):
            self.queries = []

        def execute(self, statement, params=None):
            self.queries.append((str(statement), params))

    db = MockSession()
    with transaction_context(db, user_id, workspace_id) as ctx:
        assert ctx.user_id == str(user_id)

    assert len(db.queries) == 2
    assert "edu.current_user_id" in db.queries[0][0]
    assert db.queries[0][1]["user_id"] == str(user_id)
    assert "edu.current_workspace_id" in db.queries[1][0]
    assert db.queries[1][1]["workspace_id"] == str(workspace_id)
