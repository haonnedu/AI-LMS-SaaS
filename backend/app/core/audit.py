"""AUDIT-01 minimal: one structured JSON line per sensitive mutation, with redaction.

Audit lines go through the ``eduvia`` logger hierarchy (``eduvia.audit``) using the shared
JSON formatter plus an ``audit`` object. Never pass signed URLs, object keys, tokens or raw
document content; redaction is a safety net, not a licence to log secrets.
"""

import json
import logging
import sys
from typing import Any
from uuid import UUID

from app.core.logging import JsonFormatter

REDACTED = "[REDACTED]"
SENSITIVE_PARTS = ("token", "secret", "authorization", "email", "password", "cookie")
SENSITIVE_KEYS = frozenset({"url", "signed_url", "object_key", "key"})


def _sensitive(key: str) -> bool:
    lowered = key.lower()
    return lowered in SENSITIVE_KEYS or any(part in lowered for part in SENSITIVE_PARTS)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): REDACTED if _sensitive(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [redact(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


class AuditFormatter(JsonFormatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = json.loads(super().format(record))
        audit_fields = getattr(record, "audit", None)
        if isinstance(audit_fields, dict):
            payload["audit"] = audit_fields
        return json.dumps(payload, ensure_ascii=True)


logger = logging.getLogger("eduvia.audit")


def build_audit_record(
    event: str, *, request_id: str | None, user_id: Any, workspace_id: Any, **fields: Any
) -> dict[str, Any]:
    return {
        "event": event,
        "request_id": request_id,
        "user_id": redact(user_id),
        "workspace_id": redact(workspace_id),
        **redact(fields),
    }


def audit(
    event: str, *, request_id: str | None, user_id: Any, workspace_id: Any, **fields: Any
) -> dict[str, Any]:
    record = build_audit_record(
        event, request_id=request_id, user_id=user_id, workspace_id=workspace_id, **fields
    )
    logger.info("audit." + event, extra={"audit": record})
    return record


def install_audit_handler(stream=None) -> logging.Handler:
    """Attach a JSON handler that keeps the ``audit`` object (the base formatter drops extras)."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(AuditFormatter())
    logger.handlers = [handler]
    logger.propagate = False
    # Audit events are never filtered by the application log level.
    logger.setLevel(logging.INFO)
    return handler


install_audit_handler()
