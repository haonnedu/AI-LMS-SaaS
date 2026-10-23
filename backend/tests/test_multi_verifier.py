import json
from unittest.mock import Mock

import jwt
import pytest

from app.core.auth import IdentityUnavailable, TokenError, TokenVerifierSet


def test_unverified_issuer_only_selects_fixed_verifier():
    primary = Mock(issuer="https://primary.example")
    legacy = Mock(issuer="https://legacy.example/")
    primary.verify_token.return_value = {"sub": "verified"}
    verifiers = TokenVerifierSet([primary, legacy])
    encoded = jwt.encode({"iss": primary.issuer}, "fixture" * 8, algorithm="HS256")
    assert verifiers.verify_token(encoded) == {"sub": "verified"}
    primary.verify_token.assert_called_once_with(encoded)
    legacy.verify_token.assert_not_called()


@pytest.mark.parametrize("issuer", ["https://attacker.example", None, ["invalid"]])
def test_unknown_issuer_never_fetches_keys(issuer):
    primary = Mock(issuer="https://primary.example")
    encoded = jwt.api_jws.PyJWS().encode(
        json.dumps({"iss": issuer}).encode(), "fixture" * 8, algorithm="HS256"
    )
    with pytest.raises(TokenError):
        TokenVerifierSet([primary]).verify_token(encoded)
    primary.verify_token.assert_not_called()


def test_selected_verifier_errors_do_not_fall_back_to_legacy():
    primary = Mock(issuer="https://primary.example")
    primary.verify_token.side_effect = IdentityUnavailable()
    legacy = Mock(issuer="https://legacy.example/")
    encoded = jwt.encode({"iss": primary.issuer}, "fixture" * 8, algorithm="HS256")
    with pytest.raises(IdentityUnavailable):
        TokenVerifierSet([primary, legacy]).verify_token(encoded)
    legacy.verify_token.assert_not_called()
