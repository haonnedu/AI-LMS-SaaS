import time
from types import SimpleNamespace
from unittest.mock import Mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.auth import IdentityUnavailable, TokenError, TokenVerifier


@pytest.fixture
def signing():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = TokenVerifier(
        "https://identity.example/", "eduvia-api", "https://identity.example/jwks"
    )
    verifier.jwks.get_signing_key_from_jwt = Mock(
        return_value=SimpleNamespace(key=key.public_key())
    )
    claims = {
        "iss": "https://identity.example/",
        "aud": "eduvia-api",
        "sub": "user-1",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }
    return key, verifier, claims


def token(key, claims):
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "key-1"})


def test_valid(signing):
    key, verifier, claims = signing
    assert verifier.verify_token(token(key, claims))["sub"] == "user-1"


@pytest.mark.parametrize(
    "claim,value",
    [
        ("iss", "https://evil.example/"),
        ("iss", "https://retired.auth0.com/"),
        ("aud", "other-api"),
        ("exp", 1),
        ("nbf", 9999999999),
        ("iat", 9999999999),
        ("sub", ""),
    ],
)
def test_invalid_claim(signing, claim, value):
    key, verifier, claims = signing
    claims[claim] = value
    with pytest.raises(TokenError):
        verifier.verify_token(token(key, claims))


@pytest.mark.parametrize("claim", ["iss", "aud", "sub", "exp", "iat"])
def test_required_claim(signing, claim):
    key, verifier, claims = signing
    del claims[claim]
    with pytest.raises(TokenError):
        verifier.verify_token(token(key, claims))


def test_forged_signature(signing):
    _, verifier, claims = signing
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(TokenError):
        verifier.verify_token(token(other, claims))


@pytest.mark.parametrize("alg", ["HS256", "none"])
def test_algorithm_confusion(signing, alg):
    _, verifier, claims = signing
    encoded = jwt.encode(
        claims, "s" * 32 if alg == "HS256" else "", algorithm=alg, headers={"kid": "fake"}
    )
    with pytest.raises(TokenError):
        verifier.verify_token(encoded)
    verifier.jwks.get_signing_key_from_jwt.assert_not_called()


def test_jwks_outage(signing):
    key, verifier, claims = signing
    verifier.jwks.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError(
        "private-host"
    )
    with pytest.raises(IdentityUnavailable):
        verifier.verify_token(token(key, claims))


@pytest.mark.parametrize("encoded", ["bad", "a.b.c", "x" * 17000])
def test_malformed(signing, encoded):
    with pytest.raises(TokenError):
        signing[1].verify_token(encoded)


def test_jwks_key_rotation_uses_fixed_endpoint(monkeypatch):
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from types import SimpleNamespace

    clock = [time.monotonic()]
    monkeypatch.setattr("jwt.jwks_client.time", SimpleNamespace(monotonic=lambda: clock[0]))
    keys = [rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2)]
    current = [0]
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            paths.append(self.path)
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(keys[current[0]].public_key()))
            jwk.update(kid=str(current[0]), alg="RS256", use="sig")
            body = json.dumps({"keys": [jwk]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        verifier = TokenVerifier(
            "https://issuer.example/", "api", f"http://127.0.0.1:{server.server_port}/jwks"
        )
        now = int(time.time())
        claims = {
            "iss": "https://issuer.example/",
            "aud": "api",
            "sub": "person",
            "iat": now,
            "exp": now + 300,
        }
        for index in range(2):
            current[0] = index
            clock[0] += 31  # Advance the JWKS client's anti-refresh-storm cooldown.
            encoded = jwt.encode(
                claims,
                keys[index],
                algorithm="RS256",
                headers={"kid": str(index), "jku": "http://attacker.invalid/keys"},
            )
            assert verifier.verify_token(encoded)["sub"] == "person"
        assert paths == ["/jwks", "/jwks"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
