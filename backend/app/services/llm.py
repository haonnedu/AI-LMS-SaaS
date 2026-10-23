"""Provider-neutral LLM adapter for structured drafting (AUTHR-03, ARCHITECTURE section 7).

* ``LLMProvider.complete(system, messages, *, max_tokens, json_schema) -> LLMResult``.
* ``FakeLLMProvider``: deterministic and offline (development/tests). It reads the
  ``<source id="[n]">`` blocks of the user message and returns schema-valid Vietnamese drafts
  that cite those sources, so the whole pipeline can be exercised without a network.
* ``AnthropicMessagesProvider``: stdlib ``urllib`` against ``POST /v1/messages`` with
  ``x-api-key`` and ``anthropic-version`` headers, structured output via
  ``output_config.format`` (JSON schema), per-request timeout and at most 2 retries on
  429/5xx/network errors with bounded exponential backoff (``retry-after`` honoured).

Logging never includes prompts, source text, outputs or keys: only status codes, attempts and
error types. Failures raise ``LLMError`` with a stable, client-safe ``code``.
"""

import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import SecretStr

from app.services.chunking import estimate_tokens

logger = logging.getLogger("eduvia.llm")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2026-10-21"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_ATTEMPTS = 3  # first call + at most 2 retries
MAX_BACKOFF_SECONDS = 8.0
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

_SOURCE = re.compile(r'<source id="(\[\d+\])">(.*?)</source>', re.DOTALL)


@dataclass(frozen=True)
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    request_id: str | None
    model: str


class LLMError(Exception):
    """``code`` is safe to persist and show; it never contains provider payloads."""

    def __init__(self, code: str, *, retryable: bool = False, request_id: str | None = None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.request_id = request_id


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(
        self,
        system: str,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int,
        json_schema: Mapping[str, Any] | None,
    ) -> LLMResult: ...


# ---- Fake provider --------------------------------------------------------------------------


def _first_sentence(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    for stop in (". ", "? ", "! "):
        if stop in text[:limit]:
            return text[: text.index(stop, 0, limit) + 1]
    return text[:limit].rstrip()


@dataclass
class FakeLLMProvider:
    """Deterministic drafts built only from the provided sources (no network)."""

    model: str = "fake-drafter-v1"
    name: str = "fake"
    fail_with: str | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(self, system, messages, *, max_tokens, json_schema):
        self.calls.append({"system": system, "messages": list(messages), "schema": json_schema})
        if self.fail_with:
            raise LLMError(self.fail_with, retryable=True)
        user = "\n".join(m["content"] for m in messages if m.get("role") == "user")
        sources = [(label, body) for label, body in _SOURCE.findall(user)]
        title = (json_schema or {}).get("title", "")
        if title == "questions":
            count_match = re.search(r"Số câu hỏi: (\d+)", user)
            count = int(count_match.group(1)) if count_match else 3
            payload = {"questions": [self._question(i, sources) for i in range(count)]}
        else:
            payload = self._content(sources, study_guide=title == "study_guide")
        text = json.dumps(payload, ensure_ascii=False)
        digest = hashlib.sha256((system + user).encode("utf-8")).hexdigest()[:16]
        return LLMResult(
            text=text,
            input_tokens=estimate_tokens(system) + estimate_tokens(user),
            output_tokens=estimate_tokens(text),
            request_id="fake-" + digest,
            model=self.model,
        )

    @staticmethod
    def _cite(sources, index):
        if not sources:
            return []
        label, _ = sources[index % len(sources)]
        return [{"label": label}]

    def _content(self, sources, *, study_guide: bool):
        blocks = [
            {
                "type": "paragraph",
                "text": "Tóm tắt: " + _first_sentence(_unescape(body)),
                "citations": self._cite(sources, i),
            }
            for i, (_, body) in enumerate(sources[:4])
        ] or [{"type": "note", "text": "Chưa có tài liệu nguồn phù hợp.", "citations": []}]
        first = "Kiến thức trọng tâm" if study_guide else "Mục tiêu bài học"
        return {
            "sections": [
                {
                    "heading": first,
                    "blocks": [
                        {
                            "type": "objective",
                            "text": "Học sinh nắm được nội dung chính của bài.",
                            "citations": [],
                        }
                    ],
                },
                {"heading": "Nội dung từ tài liệu", "blocks": blocks},
                {
                    "heading": "Câu hỏi ôn tập" if study_guide else "Hoạt động",
                    "blocks": [
                        {
                            "type": "activity",
                            "text": "Thảo luận nhóm và trình bày kết quả.",
                            "citations": [],
                        }
                    ],
                },
            ]
        }

    def _question(self, index, sources):
        basis = _first_sentence(_unescape(sources[index % len(sources)][1]), 120) if sources else ""
        return {
            "stem": f"Câu {index + 1}: Nhận định nào đúng theo tài liệu? {basis}".strip(),
            "choices": [
                {"key": "A", "text": f"Nhận định đúng số {index + 1}"},
                {"key": "B", "text": f"Nhận định sai thứ nhất {index + 1}"},
                {"key": "C", "text": f"Nhận định sai thứ hai {index + 1}"},
                {"key": "D", "text": f"Nhận định sai thứ ba {index + 1}"},
            ],
            "correctKey": "A",
            "explanation": "Phương án A khớp với nội dung tài liệu nguồn.",
            "cognitiveLevel": "remember",
            "citations": self._cite(sources, index),
        }


def _unescape(text: str) -> str:
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


# ---- Anthropic Messages API -----------------------------------------------------------------

Opener = Callable[..., Any]


@dataclass
class AnthropicMessagesProvider:
    api_key: SecretStr
    model: str = "claude-sonnet-5-5"
    timeout: float = 60.0
    max_attempts: int = MAX_ATTEMPTS
    server_fallback: bool = True
    url: str = ANTHROPIC_URL
    sleep: Callable[[float], None] = time.sleep
    opener: Opener = field(default=urllib.request.urlopen)
    name: str = "anthropic"

    def __post_init__(self):
        self.max_attempts = max(1, min(self.max_attempts, MAX_ATTEMPTS))

    def _request(self, system, messages, max_tokens, json_schema) -> urllib.request.Request:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": int(max_tokens),
            "system": system,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        }
        if json_schema is not None:
            schema = {k: v for k, v in json_schema.items() if k != "title"}
            body["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
        headers = {
            "x-api-key": self.api_key.get_secret_value(),
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "accept": "application/json",
        }
        if self.server_fallback:
            body["fallbacks"] = "default"
            headers["anthropic-beta"] = FALLBACK_BETA
        return urllib.request.Request(
            self.url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers=headers,
        )

    def complete(self, system, messages, *, max_tokens, json_schema):
        request = self._request(system, messages, max_tokens, json_schema)
        last_code = "provider_unavailable"
        request_id = None
        for attempt in range(1, self.max_attempts + 1):
            delay = min(MAX_BACKOFF_SECONDS, 1.0 * 2 ** (attempt - 1))
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    request_id = _header(response.headers, "request-id")
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise LLMError("provider_bad_response", request_id=request_id)
                payload = json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                request_id = _header(exc.headers, "request-id") or request_id
                logger.warning(
                    "llm_provider_error", extra={"status_code": exc.code, "attempt": attempt}
                )
                if exc.code not in RETRYABLE_STATUS:
                    code = "provider_auth_failed" if exc.code in {401, 403} else "provider_rejected"
                    raise LLMError(code, request_id=request_id) from None
                last_code = "provider_rate_limited" if exc.code == 429 else "provider_unavailable"
                retry_after = _header(exc.headers, "retry-after")
                if retry_after and retry_after.isdigit():
                    delay = min(MAX_BACKOFF_SECONDS, float(retry_after))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                logger.warning(
                    "llm_provider_unreachable",
                    extra={"error_type": type(exc).__name__, "attempt": attempt},
                )
                last_code = "provider_unavailable"
            except (ValueError, UnicodeDecodeError):
                raise LLMError("provider_bad_response", request_id=request_id) from None
            else:
                return self._result(payload, request_id)
            if attempt < self.max_attempts:
                self.sleep(delay)
        raise LLMError(last_code, retryable=True, request_id=request_id)

    def _result(self, payload: Any, request_id: str | None) -> LLMResult:
        if not isinstance(payload, dict):
            raise LLMError("provider_bad_response", request_id=request_id)
        request_id = request_id or (
            payload.get("id") if isinstance(payload.get("id"), str) else None
        )
        stop = payload.get("stop_reason")
        if stop == "refusal":
            raise LLMError("provider_refused", request_id=request_id)
        if stop == "max_tokens":
            raise LLMError("output_truncated", request_id=request_id)
        content = payload.get("content")
        if not isinstance(content, list):
            raise LLMError("provider_bad_response", request_id=request_id)
        text = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return LLMResult(
            text=text,
            input_tokens=_count(usage.get("input_tokens")),
            output_tokens=_count(usage.get("output_tokens")),
            request_id=request_id[:128] if request_id else None,
            model=str(payload.get("model") or self.model)[:128],
        )


def _header(headers, name: str) -> str | None:
    if headers is None:
        return None
    value = headers.get(name)
    return str(value)[:128] if value else None


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


class ProviderNotConfigured(Exception):
    pass


def provider_ready(settings) -> bool:
    """False when AI drafting must not run (fake provider in production)."""
    return not (settings.environment == "production" and settings.llm_provider == "fake")


def get_llm_provider(settings) -> LLMProvider:
    if not provider_ready(settings):
        raise ProviderNotConfigured("fake LLM provider is not allowed in production")
    if settings.llm_provider == "anthropic":
        return AnthropicMessagesProvider(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout_seconds,
            server_fallback=settings.llm_server_fallback,
        )
    return FakeLLMProvider()
