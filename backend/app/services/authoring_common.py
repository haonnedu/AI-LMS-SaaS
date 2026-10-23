"""Shared helpers for manual authoring services (content, question bank, blueprints).

Services expect the caller to have opened ``workspace_transaction`` and pass its scope;
RLS already confines rows to that workspace, and every query also filters ``workspace_id``.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID


class Scope(Protocol):
    """Structural view of ``WorkspaceScope`` (kept here to avoid a service -> API import)."""

    user: Any
    workspace: Any
    role: str


class AuthoringError(Exception):
    status = 400

    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message


class Invalid(AuthoringError):
    status = 422


class NotFound(AuthoringError):
    status = 404


class Forbidden(AuthoringError):
    status = 403


class Conflict(AuthoringError):
    status = 409


class RevisionConflict(Conflict):
    """Optimistic concurrency failure; carries the latest number so clients can rebase."""

    def __init__(self, latest: int, code: str = "revision_conflict", message: str | None = None):
        super().__init__(
            code,
            message or "Nội dung đã được người khác cập nhật. Vui lòng tải lại phiên bản mới nhất.",
        )
        self.latest = latest


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_json(value: Any) -> bytes:
    return hashlib.sha256(canonical_json(value)).digest()


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_uuid(value: Any) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def check_expected(latest: int, expected: int) -> None:
    if expected != latest:
        raise RevisionConflict(latest)
