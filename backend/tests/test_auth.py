"""Unit tests for server-side token verification (BE-01)."""

import base64
import hashlib
import hmac
import json
import time

import pytest

from app.core.auth import TokenError, TokenVerifier


def _create_hs256_token(payload: dict, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = (
        base64.urlsafe_b64encode(json.dumps(header).encode("utf-8")).rstrip(b"=").decode("utf-8")
    )
    payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).rstrip(b"=").decode("utf-8")
    )
    message = f"{header_b64}.{payload_b64}".encode()
    sig = hmac.new(secret.encode(), message, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode("utf-8")
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def test_valid_token():
    secret = "test-secret"
    verifier = TokenVerifier(
        expected_issuer="https://auth.eduvia.invalid",
        expected_audience="eduvia-api",
        dev_secret_key=secret,
    )
    payload_data = {
        "sub": "user-123",
        "iss": "https://auth.eduvia.invalid",
        "aud": "eduvia-api",
        "exp": int(time.time()) + 3600,
    }
    token = _create_hs256_token(payload_data, secret)
    verified = verifier.verify_token(token)
    assert verified["sub"] == "user-123"


def test_expired_token():
    secret = "test-secret"
    verifier = TokenVerifier(
        expected_issuer="https://auth.eduvia.invalid",
        expected_audience="eduvia-api",
        dev_secret_key=secret,
    )
    payload_data = {
        "sub": "user-123",
        "iss": "https://auth.eduvia.invalid",
        "aud": "eduvia-api",
        "exp": int(time.time()) - 60,
    }
    token = _create_hs256_token(payload_data, secret)
    with pytest.raises(TokenError, match="expired"):
        verifier.verify_token(token)


def test_bad_issuer():
    secret = "test-secret"
    verifier = TokenVerifier(
        expected_issuer="https://auth.eduvia.invalid",
        expected_audience="eduvia-api",
        dev_secret_key=secret,
    )
    payload_data = {
        "sub": "user-123",
        "iss": "https://spoofed-issuer.invalid",
        "aud": "eduvia-api",
        "exp": int(time.time()) + 3600,
    }
    token = _create_hs256_token(payload_data, secret)
    with pytest.raises(TokenError, match="Invalid issuer"):
        verifier.verify_token(token)


def test_bad_signature():
    verifier = TokenVerifier(
        expected_issuer="https://auth.eduvia.invalid",
        expected_audience="eduvia-api",
        dev_secret_key="correct-secret",
    )
    payload_data = {
        "sub": "user-123",
        "iss": "https://auth.eduvia.invalid",
        "aud": "eduvia-api",
        "exp": int(time.time()) + 3600,
    }
    token = _create_hs256_token(payload_data, "wrong-secret")
    with pytest.raises(TokenError, match="Invalid signature"):
        verifier.verify_token(token)
