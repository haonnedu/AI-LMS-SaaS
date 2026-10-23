import io
import json
from uuid import uuid4

import pytest

from app.core import audit as audit_module


@pytest.fixture
def captured():
    stream = io.StringIO()
    audit_module.install_audit_handler(stream)
    yield stream
    audit_module.install_audit_handler()


def test_redacts_sensitive_keys_recursively():
    record = audit_module.build_audit_record(
        "document.upload",
        request_id="req-1",
        user_id=uuid4(),
        workspace_id=uuid4(),
        access_token="eyJ.secret",
        client_secret="s",
        Authorization="Bearer x",
        email="teacher@example.com",
        nested={"userEmail": "x@example.com", "safe": 1, "items": [{"refresh_token": "r"}]},
        url="https://minio/signed?X-Amz-Signature=abc",
        object_key="ws/other/doc/1",
        size_bytes=10,
    )
    for key in ("access_token", "client_secret", "Authorization", "email", "url", "object_key"):
        assert record[key] == audit_module.REDACTED
    assert record["nested"] == {
        "userEmail": audit_module.REDACTED,
        "safe": 1,
        "items": [{"refresh_token": audit_module.REDACTED}],
    }
    assert record["size_bytes"] == 10 and record["event"] == "document.upload"


def test_audit_emits_one_structured_json_line(captured):
    user, workspace, job = uuid4(), uuid4(), uuid4()
    audit_module.audit(
        "job.cancel",
        request_id="req-2",
        user_id=user,
        workspace_id=workspace,
        job_id=job,
        token="never-logged",
    )
    lines = captured.getvalue().strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "audit.job.cancel"
    assert payload["audit"] == {
        "event": "job.cancel",
        "request_id": "req-2",
        "user_id": str(user),
        "workspace_id": str(workspace),
        "job_id": str(job),
        "token": audit_module.REDACTED,
    }
    assert "never-logged" not in captured.getvalue()
