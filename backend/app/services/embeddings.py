"""Embedding provider adapter (KNOW-06). Provider/model/dimension are still a PENDING decision
(IMPLEMENTATION_PLAN section 10), so the adapter is configurable and the default works offline.

* ``LocalHashEmbedder``: deterministic, dependency-free hashing embedder (word unigrams,
  diacritic-folded unigrams and word bigrams hashed into ``EMBEDDING_DIMENSION`` signed buckets,
  L2-normalised). DEVELOPMENT/TEST ONLY: it captures lexical overlap, not meaning, and is refused
  by the production settings validator.
* ``OpenAICompatibleEmbedder``: ``POST {base_url}/embeddings`` (OpenAI wire format) with stdlib
  ``urllib``; bearer key from a ``SecretStr``; per-request timeout; at most 3 attempts with
  exponential backoff on 429/5xx/network errors; batches of at most 64 texts; inputs truncated to
  ``MAX_INPUT_CHARS``. Every attempt is metered in ``units`` (a retried batch costs again).

Reindex rule: a vector is only comparable with vectors of the same ``(model, version)``.
``version`` encodes the dimension and an algorithm/config revision; retrieval ignores chunks whose
stored model/version differ from the configured embedder, so incompatible vectors never mix.

Logging never includes input texts, queries or vectors: only counts, status codes and attempts.
"""

import hashlib
import json
import logging
import math
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import SecretStr

from app.services.chunking import estimate_tokens

logger = logging.getLogger("eduvia.embeddings")

EMBEDDING_DIMENSION = 1024  # fixed by migration 0008_retrieval
MAX_BATCH = 64
MAX_ATTEMPTS = 3
MAX_INPUT_CHARS = 8000
MAX_BACKOFF_SECONDS = 8.0
TOKENS_PER_UNIT = 1000
LOCAL_REVISION = "1"
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

_WORD = re.compile(r"\w+", re.UNICODE)


def units_for_tokens(tokens: int) -> int:
    """1 unit per started 1000 estimated tokens, minimum 1 per call."""
    return max(1, -(-max(0, tokens) // TOKENS_PER_UNIT))


def estimate_units(texts: Sequence[str]) -> int:
    return units_for_tokens(sum(estimate_tokens(text) for text in texts))


def version_label(dimension: int, revision: str) -> str:
    return f"{dimension}d.r{revision}"


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    version: str
    units: int
    request_id: str | None = None
    request_ids: tuple[str, ...] = ()


class EmbeddingError(Exception):
    """Safe failure: ``code`` is client-visible; ``units``/``request_ids`` were consumed."""

    def __init__(
        self,
        code: str,
        *,
        units: int = 0,
        request_ids: Sequence[str] = (),
        retryable: bool = False,
    ):
        super().__init__(code)
        self.code = code
        self.units = units
        self.request_ids = tuple(request_ids)
        self.retryable = retryable


class EmbeddingProvider(Protocol):
    model: str
    version: str
    dimension: int

    def embed(self, texts: list[str]) -> EmbeddingResult: ...


def fold_diacritics(value: str) -> str:
    """Vietnamese-aware accent folding: ``Đạo hàm`` -> ``dao ham``."""
    value = value.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def tokenize(text: str) -> list[str]:
    """Lower-cased word tokens, NFC-normalised (close to PostgreSQL's ``simple`` config)."""
    return _WORD.findall(unicodedata.normalize("NFC", text).lower())


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@dataclass
class LocalHashEmbedder:
    """Deterministic hashing embedder. NOT for production quality: lexical, not semantic."""

    model: str = "local-hash-v1"
    dimension: int = EMBEDDING_DIMENSION
    revision: str = LOCAL_REVISION

    @property
    def version(self) -> str:
        return version_label(self.dimension, self.revision)

    def _features(self, text: str) -> Counter:
        tokens = tokenize(text[:MAX_INPUT_CHARS])
        features: Counter = Counter()
        for token in tokens:
            features["w:" + token] += 1.0
            folded = fold_diacritics(token)
            features["a:" + folded] += 0.5
        for left, right in zip(tokens, tokens[1:], strict=False):
            features[f"b:{left} {right}"] += 0.7
        return features

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for feature, weight in self._features(text).items():
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            sign = 1.0 if value >> 63 else -1.0
            # Sub-linear term frequency keeps repeated words from dominating.
            vector[value % self.dimension] += sign * (
                1.0 + math.log(weight) if weight > 1 else weight
            )
        return l2_normalize(vector)

    def embed(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[self._vector(text) for text in texts],
            model=self.model,
            version=self.version,
            units=estimate_units(texts) if texts else 0,
        )


Opener = Callable[..., object]


@dataclass
class OpenAICompatibleEmbedder:
    base_url: str
    api_key: SecretStr
    model: str
    dimension: int = EMBEDDING_DIMENSION
    revision: str = "1"
    timeout: float = 20.0
    batch_size: int = MAX_BATCH
    max_attempts: int = MAX_ATTEMPTS
    sleep: Callable[[float], None] = time.sleep
    opener: Opener = field(default=urllib.request.urlopen)

    def __post_init__(self):
        self.batch_size = max(1, min(self.batch_size, MAX_BATCH))
        self.max_attempts = max(1, min(self.max_attempts, MAX_ATTEMPTS))

    @property
    def version(self) -> str:
        return version_label(self.dimension, self.revision)

    @property
    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/embeddings"

    def embed(self, texts: list[str]) -> EmbeddingResult:
        vectors: list[list[float]] = []
        units = 0
        request_ids: list[str] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [text[:MAX_INPUT_CHARS] for text in texts[start : start + self.batch_size]]
            try:
                batch_vectors, batch_units, batch_ids = self._post(batch)
            except EmbeddingError as exc:
                raise EmbeddingError(
                    exc.code,
                    units=units + exc.units,
                    request_ids=request_ids + list(exc.request_ids),
                    retryable=exc.retryable,
                ) from None
            vectors.extend(batch_vectors)
            units += batch_units
            request_ids.extend(batch_ids)
        return EmbeddingResult(
            vectors=vectors,
            model=self.model,
            version=self.version,
            units=units,
            request_id=request_ids[-1] if request_ids else None,
            request_ids=tuple(request_ids),
        )

    def _request(self, batch: list[str]) -> urllib.request.Request:
        body = json.dumps(
            {"model": self.model, "input": batch, "encoding_format": "float"},
            ensure_ascii=False,
        ).encode("utf-8")
        return urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer " + self.api_key.get_secret_value(),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    def _post(self, batch: list[str]) -> tuple[list[list[float]], int, list[str]]:
        per_attempt = estimate_units(batch)
        units = 0
        request_ids: list[str] = []
        last_code = "provider_unavailable"
        for attempt in range(1, self.max_attempts + 1):
            units += per_attempt  # a retried call is billed again by the provider
            delay = min(MAX_BACKOFF_SECONDS, 0.5 * 2 ** (attempt - 1))
            try:
                with self.opener(self._request(batch), timeout=self.timeout) as response:
                    request_id = response.headers.get("x-request-id")
                    payload = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                request_id = exc.headers.get("x-request-id") if exc.headers else None
                if request_id:
                    request_ids.append(request_id[:128])
                logger.warning(
                    "embedding_provider_error",
                    extra={"status_code": exc.code, "attempt": attempt, "batch_size": len(batch)},
                )
                if exc.code not in RETRYABLE_STATUS:
                    code = "provider_auth_failed" if exc.code in {401, 403} else "provider_rejected"
                    raise EmbeddingError(code, units=units, request_ids=request_ids) from None
                last_code = "provider_rate_limited" if exc.code == 429 else "provider_unavailable"
                retry_after = exc.headers.get("retry-after") if exc.headers else None
                if retry_after and retry_after.isdigit():
                    delay = min(MAX_BACKOFF_SECONDS, float(retry_after))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                logger.warning(
                    "embedding_provider_unreachable",
                    extra={
                        "error_type": type(exc).__name__,
                        "attempt": attempt,
                        "batch_size": len(batch),
                    },
                )
                last_code = "provider_unavailable"
            except (ValueError, UnicodeDecodeError):
                raise EmbeddingError(
                    "provider_bad_response", units=units, request_ids=request_ids
                ) from None
            else:
                if request_id:
                    request_ids.append(request_id[:128])
                elif isinstance(payload, dict) and isinstance(payload.get("id"), str):
                    request_ids.append(payload["id"][:128])
                return self._vectors(payload, len(batch), units, request_ids), units, request_ids
            if attempt < self.max_attempts:
                self.sleep(delay)
        raise EmbeddingError(last_code, units=units, request_ids=request_ids, retryable=True)

    def _vectors(
        self, payload, expected: int, units: int, request_ids: list[str]
    ) -> list[list[float]]:
        def bad(code="provider_bad_response"):
            return EmbeddingError(code, units=units, request_ids=request_ids)

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or len(data) != expected:
            raise bad()
        try:
            ordered = sorted(data, key=lambda item: int(item["index"]))
        except (KeyError, TypeError, ValueError):
            raise bad() from None
        vectors = []
        for item in ordered:
            vector = item.get("embedding")
            if not isinstance(vector, list):
                raise bad()
            if len(vector) != self.dimension:
                raise bad("dimension_mismatch")
            try:
                floats = [float(v) for v in vector]
            except (TypeError, ValueError):
                raise bad() from None
            if not all(math.isfinite(v) for v in floats):
                raise bad()
            vectors.append(floats)
        return vectors


def get_embedder(settings) -> EmbeddingProvider:
    if settings.embedding_provider == "openai_compatible":
        return OpenAICompatibleEmbedder(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            dimension=settings.embedding_dimension,
            revision=settings.embedding_revision,
            timeout=settings.embedding_timeout_seconds,
            batch_size=settings.embedding_batch_size,
        )
    return LocalHashEmbedder(model=settings.embedding_model, dimension=settings.embedding_dimension)


def vector_literal(vector: Sequence[float]) -> str:
    """pgvector text input (``'[0.1,0.2,...]'``) for ``CAST(:v AS vector)``; no Python adapter."""
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"
