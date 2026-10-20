import asyncio
import re

import pytest
from fastapi.testclient import TestClient

from app.api import health
from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    settings = Settings(_env_file=None, environment="test", health_timeout_seconds=0.1)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_liveness_without_services(client):
    response = client.get("/health/live", headers={"X-Request-ID": "test-123"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "eduvia-api", "version": "0.1.0"}
    assert response.headers["x-request-id"] == "test-123"
    assert response.headers["cache-control"] == "no-store"


def test_request_id_does_not_reflect_invalid_input(client):
    response = client.get("/health/live", headers={"X-Request-ID": "a" * 200})
    assert re.fullmatch(r"[0-9a-f-]{36}", response.headers["x-request-id"])


def test_readiness_reports_real_probe_outcomes(client, monkeypatch):
    async def succeeds(_):
        return None

    monkeypatch.setattr(health, "probe_postgres", succeeds)
    monkeypatch.setattr(health, "probe_redis", succeeds)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"postgres": "ok", "redis": "ok"}}


def test_failed_dependency_is_sanitized(client, monkeypatch, caplog):
    async def fails(_):
        raise RuntimeError("postgresql://owner:DO_NOT_LEAK@private-host/eduvia")

    async def succeeds(_):
        return None

    monkeypatch.setattr(health, "probe_postgres", fails)
    monkeypatch.setattr(health, "probe_redis", succeeds)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"postgres": "unavailable", "redis": "ok"}
    assert "DO_NOT_LEAK" not in response.text
    assert "DO_NOT_LEAK" not in caplog.text


def test_slow_dependency_times_out(client, monkeypatch):
    async def slow(_):
        await asyncio.sleep(5)

    monkeypatch.setattr(health, "probe_postgres", slow)
    monkeypatch.setattr(health, "probe_redis", slow)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"postgres": "unavailable", "redis": "unavailable"}


def test_cors_allows_only_configured_origin(client):
    allowed = client.get("/health/live", headers={"Origin": "http://localhost:3000"})
    denied = client.get("/health/live", headers={"Origin": "https://untrusted.example"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in denied.headers


def test_unhandled_error_is_bounded_and_has_request_id(caplog):
    app = create_app(Settings(_env_file=None, environment="test"))

    @app.get("/test-failure")
    async def failure():
        raise ValueError("DO_NOT_LEAK_SECRET")

    with TestClient(app) as client:
        response = client.get("/test-failure", headers={"X-Request-ID": "failure-123"})
    assert response.status_code == 500
    assert response.json()["error"]["request_id"] == "failure-123"
    assert "DO_NOT_LEAK_SECRET" not in response.text
    assert "DO_NOT_LEAK_SECRET" not in caplog.text
