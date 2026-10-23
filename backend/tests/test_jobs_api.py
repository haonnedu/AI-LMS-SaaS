"""Job status/cancel/retry API (TestClient + fake verifier + fake session)."""

from uuid import uuid4

import pytest
from test_documents_api import GOOD, Harness


@pytest.fixture
def harness(monkeypatch):
    h = Harness(monkeypatch)
    yield h
    h.stub.deactivate()


def test_requires_authentication(harness):
    job_id = uuid4()
    for method, suffix in [
        ("get", "/jobs"),
        ("get", f"/jobs/{job_id}"),
        ("post", f"/jobs/{job_id}/cancel"),
        ("post", f"/jobs/{job_id}/retry"),
    ]:
        assert harness.client.request(method, harness.url(suffix)).status_code == 401


def test_cross_workspace_is_404(harness):
    job = harness.job()
    other = uuid4()
    for method, suffix in [
        ("get", "/jobs"),
        ("get", f"/jobs/{job.id}"),
        ("post", f"/jobs/{job.id}/cancel"),
        ("post", f"/jobs/{job.id}/retry"),
    ]:
        response = harness.client.request(method, harness.url(suffix, other), headers=GOOD)
        assert response.status_code == 404
    assert job.status == "queued"


def test_get_and_list(harness):
    job = harness.job("succeeded", result={"pages": None})
    harness.job()
    got = harness.client.get(harness.url(f"/jobs/{job.id}"), headers=GOOD)
    assert got.status_code == 200
    body = got.json()
    assert body["status"] == "succeeded" and body["result"] == {"pages": None}
    assert set(body) >= {"workspaceId", "maxAttempts", "cancelRequested", "errorCode"}
    assert "input" not in body and "idempotencyKey" not in body
    page = harness.client.get(harness.url("/jobs?limit=1&status=queued"), headers=GOOD).json()
    assert len(page["items"]) == 1 and page["nextCursor"]
    missing = harness.client.get(harness.url(f"/jobs/{uuid4()}"), headers=GOOD)
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "job_not_found")
    assert harness.client.get(harness.url("/jobs?status=bogus"), headers=GOOD).status_code == 422
    assert harness.client.get(harness.url("/jobs?limit=101"), headers=GOOD).status_code == 422


def test_cancel_queued_running_and_terminal(harness):
    queued, running, done = (
        harness.job(),
        harness.job("running", attempt=1),
        harness.job("succeeded"),
    )
    response = harness.client.post(harness.url(f"/jobs/{queued.id}/cancel"), headers=GOOD)
    assert response.status_code == 200 and response.json()["status"] == "cancelled"
    again = harness.client.post(harness.url(f"/jobs/{queued.id}/cancel"), headers=GOOD)
    assert again.status_code == 200 and again.json()["status"] == "cancelled"
    response = harness.client.post(harness.url(f"/jobs/{running.id}/cancel"), headers=GOOD)
    assert response.json()["status"] == "running" and response.json()["cancelRequested"]
    response = harness.client.post(harness.url(f"/jobs/{done.id}/cancel"), headers=GOOD)
    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "job_not_cancellable",
    )
    assert [event for event, _ in harness.audits] == ["job.cancel", "job.cancel"]


def test_retry_only_failed_and_dispatches_once(harness):
    failed = harness.job("failed", attempt=3, error_code="transient_error")
    response = harness.client.post(harness.url(f"/jobs/{failed.id}/retry"), headers=GOOD)
    assert response.status_code == 200
    assert (response.json()["status"], response.json()["attempt"]) == ("queued", 0)
    assert response.json()["errorCode"] is None
    again = harness.client.post(harness.url(f"/jobs/{failed.id}/retry"), headers=GOOD)
    assert again.status_code == 200 and again.json()["status"] == "queued"
    harness.dispatch.assert_awaited_once()
    cancelled = harness.job("cancelled")
    response = harness.client.post(harness.url(f"/jobs/{cancelled.id}/retry"), headers=GOOD)
    assert (response.status_code, response.json()["error"]["code"]) == (409, "job_not_retryable")
    assert [event for event, _ in harness.audits] == ["job.retry"]
