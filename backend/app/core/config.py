"""Validated environment settings; secrets are excluded from their representation."""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    environment: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    auth_issuer: str | None = None
    auth_audience: str | None = None
    auth_jwks_url: str | None = None
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://eduvia:eduvia_dev_only@localhost:5432/eduvia"
    )
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    celery_broker_url: SecretStr = SecretStr("redis://localhost:6379/1")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    health_timeout_seconds: float = Field(default=2, ge=0.1, le=10)
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "eduvia-dev"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    # Lean upload limit (STORE-01): enforced before and while reading the request body.
    upload_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1024 * 1024, le=100 * 1024 * 1024)
    # Embeddings (KNOW-06). The provider/model decision is still pending: ``local`` is a
    # deterministic hashing embedder for development/tests only and is refused in production.
    embedding_provider: Literal["local", "openai_compatible"] = "local"
    embedding_model: str = Field(default="local-hash-v1", min_length=1, max_length=128)
    # Bump to force a re-embed when a provider silently changes a model behind the same name.
    embedding_revision: str = Field(default="1", pattern=r"^[A-Za-z0-9._-]{1,16}$")
    embedding_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    # Fixed by migration 0012 (vector(1024)); another value needs a new migration + re-embed.
    embedding_dimension: int = 1024
    embedding_timeout_seconds: float = Field(default=20, ge=1, le=120)
    embedding_batch_size: int = Field(default=64, ge=1, le=64)
    # Semantic candidates farther than this cosine distance are not evidence (abstention).
    # Model-dependent: calibrate with the RAG eval set when the provider is chosen.
    retrieval_max_cosine_distance: float = Field(default=0.8, gt=0, le=2)
    # AI drafting (AUTHR-03). ``fake`` is a deterministic offline provider for development and
    # tests; production refuses it when the provider is built (``llm.get_llm_provider``) so an
    # unconfigured deployment fails AI jobs with ``provider_unavailable`` instead of inventing
    # drafts. Manual authoring never depends on these settings.
    llm_provider: Literal["fake", "anthropic"] = "fake"
    llm_model: str = Field(default="claude-sonnet-5-5", min_length=1, max_length=128)
    llm_api_key: SecretStr | None = None
    llm_max_output_tokens: int = Field(default=4000, ge=256, le=16000)
    llm_max_input_tokens: int = Field(default=12000, ge=1000, le=200000)
    llm_timeout_seconds: float = Field(default=60, ge=5, le=300)
    llm_units_per_request: int = Field(default=10, ge=1, le=1000)
    # Anthropic server-side refusal fallback (beta header + ``fallbacks: "default"``).
    llm_server_fallback: bool = True
    # Privacy/consent (PILOT-05). Legal assumptions pending review (decision 0008): students
    # younger than this need a recorded guardian consent before starting attempts.
    privacy_consent_age: int = Field(default=16, ge=12, le=18)
    # Version of the privacy notice every new consent row records.
    privacy_policy_version: str = Field(default="2026-10-draft", pattern=r"^[A-Za-z0-9._-]{1,32}$")
    # Lifetime of signed download URLs for privacy exports (capped at 300 s by storage).
    privacy_export_url_seconds: int = Field(default=300, ge=30, le=300)

    @field_validator("database_url")
    @classmethod
    def postgres_driver(cls, value: SecretStr) -> SecretStr:
        try:
            parsed = make_url(value.get_secret_value())
        except Exception:
            raise ValueError("DATABASE_URL must be a valid PostgreSQL URL") from None
        if parsed.drivername != "postgresql+psycopg" or not parsed.database:
            raise ValueError("DATABASE_URL requires postgresql+psycopg and a database name")
        return value

    @field_validator("redis_url", "celery_broker_url")
    @classmethod
    def redis_scheme(cls, value: SecretStr) -> SecretStr:
        parsed = urlsplit(value.get_secret_value())
        if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
            raise ValueError("Redis URLs require redis:// or rediss:// and a hostname")
        return value

    @field_validator("cors_origins")
    @classmethod
    def exact_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or "*" in value
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CORS_ORIGINS must contain exact HTTP(S) origins without paths")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_storage_and_production(self) -> "Settings":
        auth_values = (self.auth_issuer, self.auth_audience, self.auth_jwks_url)
        if any(auth_values) and not all(auth_values):
            raise ValueError("Set AUTH_ISSUER, AUTH_AUDIENCE and AUTH_JWKS_URL together")
        for endpoint in (
            self.auth_issuer,
            self.auth_jwks_url,
        ):
            if endpoint:
                parsed = urlsplit(endpoint)
                local_test = self.environment != "production" and parsed.hostname in {
                    "127.0.0.1",
                    "localhost",
                }
                if (
                    (parsed.scheme != "https" and not local_test)
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.fragment
                ):
                    raise ValueError("Identity endpoints require fixed HTTPS URLs")
        if self.embedding_dimension != 1024:
            raise ValueError("EMBEDDING_DIMENSION is fixed at 1024 by migration 0012_retrieval")
        if self.embedding_provider == "openai_compatible":
            if not self.embedding_base_url or not self.embedding_api_key:
                raise ValueError("openai_compatible embeddings need EMBEDDING_BASE_URL and key")
            parsed = urlsplit(self.embedding_base_url)
            local_dev = self.environment != "production" and parsed.hostname in {
                "127.0.0.1",
                "localhost",
            }
            if (
                (parsed.scheme != "https" and not local_dev)
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("EMBEDDING_BASE_URL requires a fixed HTTPS URL")
        if self.llm_provider == "anthropic" and not self.llm_api_key:
            raise ValueError("LLM_PROVIDER=anthropic requires LLM_API_KEY")
        if bool(self.s3_access_key_id) != bool(self.s3_secret_access_key):
            raise ValueError("Set both S3 credential fields or use the default credential chain")
        if self.environment == "production":
            database = make_url(self.database_url.get_secret_value())
            if database.password in {
                "eduvia_dev_only",
                "runtime_dev_only",
                "migrator_dev_only",
                "runtime_test_only",
                "auth_test_only",
            }:
                raise ValueError("Production requires a non-development database credential")
            if self.s3_secret_access_key and (
                self.s3_secret_access_key.get_secret_value() == "eduvia_dev_only"
            ):
                raise ValueError("Production requires a non-development object-storage credential")
            if any(not origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("Production CORS origins require HTTPS")
            if self.embedding_provider == "local":
                raise ValueError("The local hashing embedder is for development/tests only")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
