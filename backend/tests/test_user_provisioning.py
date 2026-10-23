"""Atomic provisioning is exercised against PostgreSQL in test_identity_integration."""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.core.auth import CLAIM_NAMESPACE
from app.services.user_provisioning import provision_user_from_claims


async def test_bootstrap_passes_only_verified_profile():
    actor = uuid4()
    db = AsyncMock()
    db.execute.return_value = Mock(scalar_one=Mock(return_value=actor))
    result = await provision_user_from_claims(
        db,
        {
            "iss": "issuer",
            "sub": "subject",
            CLAIM_NAMESPACE + "email": "teacher@example.com",
            "owner": "attacker",
        },
    )
    assert result == actor
    statement, params = db.execute.call_args.args
    assert "bootstrap_identity" in str(statement)
    assert params == {"email": "teacher@example.com", "name": "Giáo viên"}
