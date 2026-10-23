"""Verify API access tokens against a fixed issuer and JWKS endpoint."""

from typing import Any

import jwt
from jwt import PyJWKClient

CLAIM_NAMESPACE = "https://eduvia.app/claims/"


class TokenError(ValueError):
    pass


class IdentityUnavailable(RuntimeError):
    pass


class TokenVerifier:
    def __init__(self, expected_issuer: str, expected_audience: str, jwks_url: str):
        self.issuer = expected_issuer
        self.audience = expected_audience
        self.jwks = PyJWKClient(jwks_url, timeout=5, lifespan=300)

    def verify_token(self, token: str) -> dict[str, Any]:
        if len(token) > 16384:
            raise TokenError("Invalid token")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise TokenError("Invalid token")
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                leeway=30,
                options={"require": ["iss", "aud", "sub", "exp", "iat"]},
            )
            if not isinstance(claims["sub"], str) or not claims["sub"] or len(claims["sub"]) > 255:
                raise TokenError("Invalid subject")
            return claims
        except jwt.PyJWKClientConnectionError as exc:
            raise IdentityUnavailable("Identity provider unavailable") from exc
        except jwt.PyJWTError as exc:
            raise TokenError("Invalid token") from exc
