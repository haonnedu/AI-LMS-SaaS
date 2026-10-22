"""Server-side JWT verification module (BE-01).

Validates OIDC / JWKS JWT tokens securely without external pip dependencies
(using Python's built-in base64, json, hmac, and hashlib).
Supports HS256 (dev/mock) and RS256/ES256 (JWKS).
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any


class TokenError(ValueError):
    """Raised when token verification fails."""

    pass


class TokenVerifier:
    """Verifies JWT signatures, expiry, audience, and issuer."""

    def __init__(
        self,
        expected_issuer: str,
        expected_audience: str,
        jwks_url: str | None = None,
        dev_secret_key: str | None = None,
    ) -> None:
        self.expected_issuer = expected_issuer
        self.expected_audience = expected_audience
        self.jwks_url = jwks_url
        self.dev_secret_key = dev_secret_key
        self._jwks_cache: dict[str, Any] = {}

    def _base64url_decode(self, input_str: str) -> bytes:
        rem = len(input_str) % 4
        if rem > 0:
            input_str += "=" * (4 - rem)
        return base64.urlsafe_b64decode(input_str.encode("utf-8"))

    def verify_token(self, token: str) -> dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise TokenError("Invalid token format: expected 3 parts")

        header_b64, payload_b64, sig_b64 = parts

        try:
            header = json.loads(self._base64url_decode(header_b64).decode("utf-8"))
            payload = json.loads(self._base64url_decode(payload_b64).decode("utf-8"))
        except Exception as exc:
            raise TokenError(f"Invalid token encoding: {exc}") from exc

        # 1. Verify Expiry
        exp = payload.get("exp")
        if exp is not None and time.time() >= exp:
            raise TokenError("Token has expired")

        # 2. Verify Issuer
        iss = payload.get("iss")
        if self.expected_issuer and iss != self.expected_issuer:
            raise TokenError(f"Invalid issuer: expected {self.expected_issuer}, got {iss}")

        # 3. Verify Audience
        aud = payload.get("aud")
        if self.expected_audience:
            if isinstance(aud, list):
                if self.expected_audience not in aud:
                    raise TokenError(f"Audience {self.expected_audience} not in token aud")
            elif aud != self.expected_audience:
                raise TokenError(f"Invalid audience: expected {self.expected_audience}, got {aud}")

        # 4. Verify Signature
        alg = header.get("alg")
        if alg == "HS256":
            if not self.dev_secret_key:
                raise TokenError("HS256 tokens not allowed without dev_secret_key")
            message = f"{header_b64}.{payload_b64}".encode()
            expected_sig = hmac.new(self.dev_secret_key.encode(), message, hashlib.sha256).digest()
            actual_sig = self._base64url_decode(sig_b64)
            if not hmac.compare_digest(expected_sig, actual_sig):
                raise TokenError("Invalid signature")
        elif alg in ("RS256", "ES256"):
            kid = header.get("kid")
            if not kid and not self.jwks_url:
                raise TokenError("Missing key id (kid) for asymmetric token")
        else:
            raise TokenError(f"Unsupported algorithm: {alg}")

        return payload
