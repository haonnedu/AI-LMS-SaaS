"""Shared assessment errors, constants and SQLSTATE mapping (M5/M6).

Services raise ``AssessmentError`` subclasses with Vietnamese client messages; routers turn
them into the standard error envelope. Database outcomes of the student SECURITY DEFINER
functions (migration 0015) are mapped by ``map_db_error``.
"""

from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy.exc import DBAPIError

# Transport grace after ``deadline_at`` (mirrors ``interval '5 seconds'`` in migration 0015).
GRACE = timedelta(seconds=5)
STAFF_ROLES = frozenset({"owner", "admin", "teacher"})


class Scope(Protocol):
    """Structural view of ``WorkspaceScope`` (kept here to avoid a service -> API import)."""

    user: Any
    workspace: Any
    role: str


class AssessmentError(Exception):
    status = 400

    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message


class Invalid(AssessmentError):
    status = 422


class NotFound(AssessmentError):
    status = 404


class Forbidden(AssessmentError):
    status = 403


class Conflict(AssessmentError):
    status = 409


ASSIGNMENT_NOT_FOUND = ("assignment_not_found", "Không tìm thấy bài được giao.")
ATTEMPT_NOT_FOUND = ("attempt_not_found", "Không tìm thấy lượt làm bài.")

# SQLSTATE -> client error. Kept in one table so every caller maps outcomes identically.
DB_ERRORS: dict[str, AssessmentError] = {
    "P0002": NotFound("not_found", "Không tìm thấy dữ liệu yêu cầu."),
    "28000": Forbidden("account_disabled", "Tài khoản này đã bị vô hiệu hoá."),
    "22023": Invalid("invalid_request", "Yêu cầu không hợp lệ."),
    "EV010": Conflict("attempt_expired", "Đã hết thời gian làm bài; câu trả lời không được lưu."),
    "EV011": Conflict("idempotency_conflict", "Idempotency-Key đã được dùng cho một yêu cầu khác."),
    "EV012": Conflict("assignment_unavailable", "Bài được giao hiện không mở để làm."),
    "EV013": Conflict("attempt_limit_reached", "Bạn đã dùng hết số lượt làm bài."),
    "EV014": Conflict(
        "stale_answer", "Câu trả lời đã được cập nhật ở nơi khác; hãy tải lại bài làm."
    ),
    "EV015": Conflict("attempt_closed", "Lượt làm bài đã được nộp."),
    "EV016": Invalid("invalid_option", "Lựa chọn không thuộc câu hỏi này."),
}


def sqlstate(exc: BaseException) -> str | None:
    return getattr(getattr(exc, "orig", None), "sqlstate", None)


def map_db_error(exc: DBAPIError, *, not_found: tuple[str, str] | None = None) -> Exception:
    """Translate a definer-function failure; unknown states are re-raised unchanged."""
    state = sqlstate(exc) or ""
    if state == "P0002" and not_found is not None:
        return NotFound(*not_found)
    mapped = DB_ERRORS.get(state)
    if mapped is None:
        return exc
    return type(mapped)(mapped.code, mapped.message)
