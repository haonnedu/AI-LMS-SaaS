"""Embedding adapters (KNOW-06): local determinism/normalisation, OpenAI-compatible batching,
retries metered as units, failure codes, settings validation, and no text in logs."""

import io
import json
import logging
import math
import urllib.error
from email.message import Message

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.services import embeddings
from app.services.embeddings import (
    EmbeddingError,
    LocalHashEmbedder,
    OpenAICompatibleEmbedder,
    cosine_similarity,
    get_embedder,
)

SECRET_TEXT = "Bí mật của giáo viên: đề thi học kì"
API_KEY = "sk-test-not-a-real-key"


def norm(vector):
    return math.sqrt(sum(v * v for v in vector))


# ---------------------------------------------------------------- local hashing embedder


def test_local_embedder_is_deterministic_normalised_and_versioned():
    embedder = LocalHashEmbedder()
    first = embedder.embed(["Mệnh đề là một câu khẳng định", "Đạo hàm"])
    second = LocalHashEmbedder().embed(["Mệnh đề là một câu khẳng định", "Đạo hàm"])
    assert first.vectors == second.vectors
    assert all(len(v) == embeddings.EMBEDDING_DIMENSION for v in first.vectors)
    assert all(abs(norm(v) - 1.0) < 1e-9 for v in first.vectors)
    assert (first.model, first.version) == ("local-hash-v1", "1024d.r1")
    assert first.units == 1 and first.request_id is None


def test_local_embedder_reflects_overlap_and_folds_diacritics():
    embedder = LocalHashEmbedder()
    base, related, unrelated, folded = embedder.embed(
        [
            "Đạo hàm của hàm số hằng bằng 0",
            "đạo hàm của hàm số",
            "Truyện Kiều của Nguyễn Du",
            "dao ham cua ham so",
        ]
    ).vectors
    assert cosine_similarity(base, related) > cosine_similarity(base, unrelated)
    assert cosine_similarity(base, folded) > cosine_similarity(base, unrelated)
    assert embeddings.fold_diacritics("Đạo hàm") == "Dao ham"


def test_local_embedder_handles_empty_and_punctuation():
    result = LocalHashEmbedder().embed(["---", ""])
    assert all(norm(v) == 0 for v in result.vectors)
    assert LocalHashEmbedder().embed([]).units == 0


def test_units_and_vector_literal():
    assert embeddings.units_for_tokens(0) == 1
    assert embeddings.units_for_tokens(1000) == 1
    assert embeddings.units_for_tokens(1001) == 2
    assert embeddings.vector_literal([0.5, -1, 0]) == "[0.5,-1.0,0.0]"


# ---------------------------------------------------------------- OpenAI-compatible adapter


class FakeResponse:
    def __init__(self, payload, request_id="req-1"):
        self.body = json.dumps(payload).encode()
        self.headers = {"x-request-id": request_id} if request_id else {}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, retry_after=None):
    headers = Message()
    headers["x-request-id"] = f"err-{code}"
    if retry_after:
        headers["retry-after"] = retry_after
    return urllib.error.HTTPError("https://x/embeddings", code, "err", headers, io.BytesIO(b""))


class FakeOpener:
    def __init__(self, *outcomes, dimension=4):
        self.outcomes = list(outcomes)
        self.dimension = dimension
        self.requests = []

    def __call__(self, request, timeout):
        body = json.loads(request.data)
        self.requests.append((request, body, timeout))
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        if isinstance(outcome, Exception):
            raise outcome
        if outcome == "ok":
            data = [
                {"index": i, "embedding": [0.1 * (i + 1)] * self.dimension}
                for i in reversed(range(len(body["input"])))  # out of order on purpose
            ]
            return FakeResponse({"data": data})
        return FakeResponse(outcome)


def provider(opener, **overrides):
    values = dict(
        base_url="https://embeddings.example/v1/",
        api_key=SecretStr(API_KEY),
        model="test-embed",
        dimension=4,
        sleep=lambda _s: None,
        opener=opener,
    )
    values.update(overrides)
    return OpenAICompatibleEmbedder(**values)


def test_batches_of_at_most_64_and_request_shape():
    opener = FakeOpener()
    result = provider(opener).embed([f"đoạn {i}" for i in range(130)])
    assert [len(body["input"]) for _, body, _ in opener.requests] == [64, 64, 2]
    request, body, timeout = opener.requests[0]
    assert request.full_url == "https://embeddings.example/v1/embeddings"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer " + API_KEY
    assert body["model"] == "test-embed" and timeout == 20.0
    assert len(result.vectors) == 130 and result.vectors[0] == [0.1] * 4  # re-ordered by index
    assert result.units == 3 and result.request_ids == ("req-1",) * 3
    assert result.version == "4d.r1"


def test_batch_size_is_capped_and_inputs_truncated():
    opener = FakeOpener()
    provider(opener, batch_size=500).embed(["x" * 20000] * 70)
    assert [len(body["input"]) for _, body, _ in opener.requests] == [64, 6]
    assert all(len(t) == embeddings.MAX_INPUT_CHARS for t in opener.requests[0][1]["input"])


def test_retry_then_success_meters_every_attempt():
    sleeps = []
    opener = FakeOpener(http_error(503), http_error(429, retry_after="2"), "ok")
    result = provider(opener, sleep=sleeps.append).embed(["a", "b"])
    assert len(opener.requests) == 3
    assert result.units == 3  # 1 unit per attempt
    assert sleeps == [0.5, 2.0]
    assert result.request_ids == ("err-503", "err-429", "req-1")


def test_exhausted_retries_fail_with_units_and_no_more_than_three_attempts():
    opener = FakeOpener(http_error(500), urllib.error.URLError("down"), TimeoutError())
    with pytest.raises(EmbeddingError) as raised:
        provider(opener, max_attempts=10).embed(["a"])
    assert len(opener.requests) == 3
    assert raised.value.code == "provider_unavailable" and raised.value.retryable
    assert raised.value.units == 3


@pytest.mark.parametrize(
    "outcome,code",
    [
        (http_error(401), "provider_auth_failed"),
        (http_error(400), "provider_rejected"),
        ({"data": [{"index": 0, "embedding": [1.0, 2.0]}]}, "dimension_mismatch"),
        ({"data": []}, "provider_bad_response"),
        ({"data": [{"index": 0, "embedding": [float("nan")] * 4}]}, "provider_bad_response"),
    ],
)
def test_permanent_failures_are_not_retried(outcome, code):
    opener = FakeOpener(outcome)
    with pytest.raises(EmbeddingError) as raised:
        provider(opener).embed(["a"])
    assert raised.value.code == code and not raised.value.retryable
    assert len(opener.requests) == 1 and raised.value.units == 1


def test_failure_in_second_batch_keeps_units_of_first():
    opener = FakeOpener("ok", http_error(403))
    with pytest.raises(EmbeddingError) as raised:
        provider(opener, batch_size=1).embed(["a", "b"])
    assert raised.value.units == 2 and raised.value.request_ids[0] == "req-1"


def test_logs_never_contain_texts_or_key(caplog):
    caplog.set_level(logging.DEBUG)
    opener = FakeOpener(http_error(503), http_error(503), http_error(503))
    with pytest.raises(EmbeddingError):
        provider(opener).embed([SECRET_TEXT])
    assert caplog.records  # retries were logged...
    for record in caplog.records:
        rendered = record.getMessage() + json.dumps(vars(record), default=str, ensure_ascii=False)
        assert SECRET_TEXT not in rendered and "đề thi" not in rendered  # ...without the text
        assert API_KEY not in rendered


# ---------------------------------------------------------------- settings and factory


def test_factory_defaults_to_local_and_builds_remote():
    assert isinstance(get_embedder(Settings(_env_file=None)), LocalHashEmbedder)
    remote = get_embedder(
        Settings(
            _env_file=None,
            embedding_provider="openai_compatible",
            embedding_model="vendor-embed-1",
            embedding_base_url="https://api.vendor.example/v1",
            embedding_api_key="secret-value",
        )
    )
    assert isinstance(remote, OpenAICompatibleEmbedder)
    assert remote.model == "vendor-embed-1" and remote.version == "1024d.r1"
    assert "secret-value" not in repr(remote)


@pytest.mark.parametrize(
    "overrides",
    [
        {"embedding_provider": "openai_compatible"},
        {
            "embedding_provider": "openai_compatible",
            "embedding_base_url": "http://api.vendor.example/v1",
            "embedding_api_key": "k",
        },
        {
            "embedding_provider": "openai_compatible",
            "embedding_base_url": "https://user:pw@api.vendor.example/v1",
            "embedding_api_key": "k",
        },
    ],
)
def test_remote_provider_settings_are_validated(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_production_refuses_local_embedder():
    production = dict(
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg://app:strong-secret@db/eduvia",
        cors_origins=["https://eduvia.example"],
    )
    with pytest.raises(ValidationError, match="development/tests only"):
        Settings(**production)
    settings = Settings(
        **production,
        embedding_provider="openai_compatible",
        embedding_model="vendor-embed-1",
        embedding_base_url="https://api.vendor.example/v1",
        embedding_api_key="secret-value",
    )
    assert settings.embedding_provider == "openai_compatible"
