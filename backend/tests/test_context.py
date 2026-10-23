from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.infrastructure.context import transaction_context


async def test_transaction_context_manager():
    user, workspace = uuid4(), uuid4()
    db = AsyncMock()
    async with transaction_context(db, user, workspace) as ctx:
        assert ctx.user_id == str(user)
    statement, params = db.execute.call_args.args
    assert "set_config" in str(statement) and "true" in str(statement)
    assert params == {"user_id": str(user), "workspace_id": str(workspace)}


async def test_reject_invalid_context():
    with pytest.raises(ValueError):
        async with transaction_context(AsyncMock(), "untrusted", uuid4()):
            pass
