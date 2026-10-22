"""Tests for idempotent user provisioning (BE-02)."""

from unittest.mock import MagicMock

import pytest

from app.models.identity import User
from app.services.user_provisioning import provision_user_from_claims


def test_provision_new_user():
    db = MagicMock()
    db.scalars.return_value.first.return_value = None

    claims = {"sub": "sub-123", "email": "test@example.com", "name": "Test User"}
    user = provision_user_from_claims(db, claims)

    assert user.provider_sub == "sub-123"
    assert user.email == "test@example.com"
    assert user.display_name == "Test User"
    db.add.assert_called_once()
    db.flush.assert_called_once()


def test_provision_idempotent_existing_user():
    db = MagicMock()
    existing_user = User(
        id="11111111-1111-1111-1111-111111111111",
        provider_sub="sub-123",
        email="old@example.com",
        display_name="Old Name",
    )
    db.scalars.return_value.first.side_effect = [existing_user, None]

    claims = {"sub": "sub-123", "email": "new@example.com", "name": "New Name"}
    user = provision_user_from_claims(db, claims)

    assert user is existing_user
    assert user.email == "new@example.com"
    assert user.display_name == "New Name"
    db.flush.assert_called_once()


def test_provision_email_collision_raises_error():
    db = MagicMock()
    other_user = User(
        id="22222222-2222-2222-2222-222222222222",
        provider_sub="sub-other",
        email="conflict@example.com",
        display_name="Other",
    )
    db.scalars.return_value.first.side_effect = [None, other_user]

    claims = {"sub": "sub-123", "email": "conflict@example.com", "name": "Hacker"}
    with pytest.raises(ValueError, match="Email already registered"):
        provision_user_from_claims(db, claims)
