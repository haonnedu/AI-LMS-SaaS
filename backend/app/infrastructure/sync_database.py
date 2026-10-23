"""Synchronous engine for Celery workers (same DATABASE_URL and runtime role as the API)."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


def create_sync_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        pool_timeout=settings.health_timeout_seconds,
        hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )


@lru_cache
def get_sync_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(create_sync_engine(get_settings()), expire_on_commit=False, autoflush=False)


def set_actor_context(
    db: Session, *, issuer: str, subject: str, user_id: str, workspace_id: str
) -> None:
    """Transaction-local, like the API: pool reuse can never retain another job's context."""
    db.execute(
        text(
            "SELECT set_config('edu.issuer', :issuer, true), "
            "set_config('edu.subject', :subject, true), "
            "set_config('edu.current_user_id', :user_id, true), "
            "set_config('edu.current_workspace_id', :workspace_id, true)"
        ),
        {
            "issuer": issuer,
            "subject": subject,
            "user_id": str(user_id),
            "workspace_id": str(workspace_id),
        },
    )
