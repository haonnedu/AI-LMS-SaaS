"""JSON application logs containing only deliberately selected fields."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "request_id": request_id_context.get(),
        }
        for key in ("method", "route", "status_code", "duration_ms", "dependency", "error_type"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        # Exception text and tracebacks are intentionally excluded: connection errors
        # and upstream messages may contain passwords, documents, or signed URLs.
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(level: str) -> None:
    logger = logging.getLogger("eduvia")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
