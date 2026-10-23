"""LLM adapter: deterministic fake provider and the Anthropic adapter over fake HTTP."""

import io
import json
import logging
import urllib.error
from email.message import Message
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.services import generation, llm

SYSTEM = "Lời nhắc hệ thống cố định"
PROMPT = 'Bí mật đề bài <source id="[1]">Phân số là số có dạng a/b.</source>'
KEY = "sk-test-very-secret"


def headers(**values):
    message = Message()
    for name, value in values.items():
        message[name.replace("_", "-")] = value
    return message


class FakeResponse:
    def __init__(self, payload, request_id="req_123"):
        self._data = json.dumps(payload).encode()
        self.headers = headers(request_id=request_id)

    def read(self, limit=-1):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ok_payload(text='{"sections": []}', stop="end_turn"):
    return {
        "id": "msg_1",
        "model": "claude-sonnet-5-5",
        "stop_reason": stop,
        "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}],
        "usage": {"input_tokens": 120, "output_tokens": 40},
    }


class Opener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def http_error(code, retry_after=None):
    extra = {"request_id": f"req_{code}"}
    if retry_after:
        extra["retry_after"] = retry_after
    return urllib.error.HTTPError(
        "https://api.anthropic.com/v1/messages", code, "err", headers(**extra), io.BytesIO(b"{}")
    )


def provider(outcomes, sleeps):
    opener = Opener(outcomes)
    return (
        llm.AnthropicMessagesProvider(
            api_key=SecretStr(KEY), timeout=12, opener=opener, sleep=sleeps.append
        ),
        opener,
    )


def complete(adapter, schema=None):
    return adapter.complete(
        SYSTEM,
        [{"role": "user", "content": PROMPT}],
        max_tokens=500,
        json_schema=schema or generation.content_schema("lesson_plan"),
    )


def test_request_shape_and_result():
    sleeps = []
    adapter, opener = provider([FakeResponse(ok_payload())], sleeps)
    result = complete(adapter)
    assert result == llm.LLMResult('{"sections": []}', 120, 40, "req_123", "claude-sonnet-5-5")
    request = opener.requests[0]
    assert request.full_url == "https://api.anthropic.com/v1/messages"
    assert request.get_header("X-api-key") == KEY
    assert request.get_header("Anthropic-version") == llm.ANTHROPIC_VERSION
    assert request.get_header("Anthropic-beta") == llm.FALLBACK_BETA
    body = json.loads(request.data)
    assert body["model"] == "claude-sonnet-5-5" and body["max_tokens"] == 500
    assert body["system"] == SYSTEM and body["messages"][0]["content"] == PROMPT
    schema = body["output_config"]["format"]
    assert schema["type"] == "json_schema" and "title" not in schema["schema"]
    assert not {"temperature", "top_p", "top_k"} & set(body)
    assert opener.timeouts == [12] and sleeps == []


@pytest.mark.parametrize("code", [429, 500, 503, 529])
def test_retries_transient_errors_at_most_twice(code):
    sleeps = []
    adapter, opener = provider([http_error(code), http_error(code), http_error(code)], sleeps)
    with pytest.raises(llm.LLMError) as error:
        complete(adapter)
    assert len(opener.requests) == 3  # first call + 2 retries
    assert len(sleeps) == 2 and all(0 < s <= llm.MAX_BACKOFF_SECONDS for s in sleeps)
    expected = "provider_rate_limited" if code == 429 else "provider_unavailable"
    assert error.value.code == expected and error.value.retryable


def test_retry_then_success_honours_retry_after():
    sleeps = []
    adapter, opener = provider([http_error(429, "3"), FakeResponse(ok_payload())], sleeps)
    assert complete(adapter).output_tokens == 40
    assert sleeps == [3.0] and len(opener.requests) == 2


@pytest.mark.parametrize(
    "outcome", [TimeoutError("timed out"), urllib.error.URLError("unreachable")]
)
def test_timeouts_and_network_errors_become_provider_unavailable(outcome):
    sleeps = []
    adapter, opener = provider([outcome, outcome, outcome], sleeps)
    with pytest.raises(llm.LLMError) as error:
        complete(adapter)
    assert error.value.code == "provider_unavailable" and len(opener.requests) == 3


@pytest.mark.parametrize(
    "code,expected", [(400, "provider_rejected"), (401, "provider_auth_failed")]
)
def test_client_errors_are_not_retried(code, expected):
    sleeps = []
    adapter, opener = provider([http_error(code)], sleeps)
    with pytest.raises(llm.LLMError) as error:
        complete(adapter)
    assert error.value.code == expected and len(opener.requests) == 1 and sleeps == []


@pytest.mark.parametrize(
    "stop,code", [("refusal", "provider_refused"), ("max_tokens", "output_truncated")]
)
def test_stop_reasons(stop, code):
    adapter, _ = provider([FakeResponse(ok_payload(stop=stop))], [])
    with pytest.raises(llm.LLMError) as error:
        complete(adapter)
    assert error.value.code == code


def test_bad_json_response():
    response = FakeResponse({})
    response._data = b"not json"
    adapter, _ = provider([response], [])
    with pytest.raises(llm.LLMError) as error:
        complete(adapter)
    assert error.value.code == "provider_bad_response"


def test_logs_never_contain_prompt_or_key(caplog):
    caplog.set_level(logging.DEBUG)
    adapter, _ = provider([http_error(500), TimeoutError(), FakeResponse(ok_payload())], [])
    complete(adapter)
    assert caplog.records
    for record in caplog.records:
        dumped = json.dumps(record.__dict__, default=str)
        assert KEY not in dumped and "Bí mật" not in dumped and "Phân số" not in dumped
        assert SYSTEM not in dumped


def test_fake_provider_is_deterministic_and_schema_valid():
    fake = llm.FakeLLMProvider()
    request = {
        "purpose": "questions",
        "subject": "Toán",
        "grade": 6,
        "objectives": ["Phân số"],
        "count": 3,
        "curriculumUnitId": "00000000-0000-0000-0000-000000000001",
    }
    sources = [generation.PromptSource("[1]", uuid4(), "Phân số a/b.", b"0" * 32, 1)]
    user = generation.build_user_message(request, sources)
    messages = [{"role": "user", "content": user}]
    first = fake.complete("s", messages, max_tokens=100, json_schema=generation.QUESTIONS_SCHEMA)
    second = fake.complete("s", messages, max_tokens=100, json_schema=generation.QUESTIONS_SCHEMA)
    assert first == second
    parsed = json.loads(first.text)
    assert generation.check_schema(parsed, generation.QUESTIONS_SCHEMA) == []
    assert len(parsed["questions"]) == 3
    assert {c["label"] for q in parsed["questions"] for c in q["citations"]} == {"[1]"}
    lesson = fake.complete(
        "s", messages, max_tokens=100, json_schema=generation.content_schema("lesson_plan")
    )
    body = json.loads(lesson.text)
    assert generation.check_schema(body, generation.content_schema("lesson_plan")) == []
    assert "Phân số" in lesson.text  # built from the provided source


def test_fake_provider_outage():
    with pytest.raises(llm.LLMError) as error:
        llm.FakeLLMProvider(fail_with="provider_unavailable").complete(
            "s", [], max_tokens=1, json_schema=None
        )
    assert error.value.code == "provider_unavailable"


def test_provider_factory_and_settings():
    base = dict(_env_file=None)
    assert isinstance(llm.get_llm_provider(Settings(**base)), llm.FakeLLMProvider)
    configured = Settings(**base, llm_provider="anthropic", llm_api_key="sk-x", llm_model="m")
    adapter = llm.get_llm_provider(configured)
    assert isinstance(adapter, llm.AnthropicMessagesProvider) and adapter.model == "m"
    assert "sk-x" not in repr(configured)
    with pytest.raises(ValidationError):
        Settings(**base, llm_provider="anthropic")
    production = Settings(**base, llm_provider="fake").model_copy(
        update={"environment": "production"}
    )
    assert not llm.provider_ready(production)
    with pytest.raises(llm.ProviderNotConfigured):
        llm.get_llm_provider(production)
