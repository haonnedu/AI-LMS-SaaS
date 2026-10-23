"""Idempotent user provisioning service (BE-02).

Provisions or retrieves a user record based on the stable provider subject (provider_sub).
Does not merge or overwrite accounts on email collision; email updates are handled
explicitly via verified provider claims.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import User


def provision_user_from_claims(db: Session, claims: dict[str, Any]) -> User:
    """Idempotently provision or retrieve a user from verified token claims.

    Identifies users strictly by their stable provider subject (`sub`).
    """
    provider_sub = claims.get("sub")
    email = claims.get("email")
    display_name = claims.get("name") or claims.get("preferred_username") or email

    if not provider_sub:
        raise ValueError("Claims missing required 'sub' (provider subject) claim")

    # 1. Lookup existing user by stable provider_sub
    # We use db.scalars to support mock or real sessions correctly.
    result = db.scalars(select(User).where(User.provider_sub == provider_sub)).first()

    if result:
        updated = False
        if email and result.email != email:
            existing_email_user = db.scalars(
                select(User).where(User.email == email, User.provider_sub != provider_sub)
            ).first()
            if existing_email_user:
                raise ValueError("Email is already associated with another account")
            result.email = email
            updated = True
        if display_name and result.display_name != display_name:
            result.display_name = display_name
            updated = True
        if updated:
            db.flush()
        return result

    # 2. Check if email exists with a different provider_sub
    if email:
        existing_email_user = db.scalars(select(User).where(User.email == email)).first()
        if existing_email_user:
            raise ValueError("Email already registered with a different identity provider account")

    # 3. Create new user record
    new_user = User(
        email=email or f"{provider_sub}@placeholder.invalid",
        provider_sub=provider_sub,
        display_name=display_name,
        is_active=True,
    )
    db.add(new_user)
    db.flush()
    return new_user
