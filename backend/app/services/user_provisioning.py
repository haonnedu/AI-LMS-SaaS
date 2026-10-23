"""Atomic restricted bootstrap; never merge identities by email."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CLAIM_NAMESPACE


async def provision_user_from_claims(db: AsyncSession, claims: dict[str, Any]):
    result = await db.execute(
        text("SELECT edu.bootstrap_identity(:email, :name)"),
        {
            "email": claims[CLAIM_NAMESPACE + "email"],
            "name": str(claims.get(CLAIM_NAMESPACE + "name") or "Giáo viên")[:255],
        },
    )
    return result.scalar_one()
