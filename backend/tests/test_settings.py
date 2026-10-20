import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_app_environment_uses_documented_variable(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    assert Settings(_env_file=None).environment == "test"


@pytest.mark.parametrize(
    "origin", ["*", "https://example.com/path", "http://user:pass@example.com"]
)
def test_cors_rejects_wildcard_or_non_origin(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=[origin])


def test_database_driver_is_postgresql_psycopg():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite:///example.db")


def test_settings_repr_masks_secrets():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:hidden-password@localhost/eduvia",
    )
    assert "hidden-password" not in repr(settings)


def test_production_rejects_development_credentials():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", cors_origins=["https://eduvia.example"])


def test_partial_storage_credentials_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, s3_access_key_id="local-access")
