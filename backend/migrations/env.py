"""Sync migration engine intentionally separate from the API's async connections."""

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.infrastructure.database import Base
from app.models import (
    assessment,  # noqa: F401
    authoring,  # noqa: F401
    documents,  # noqa: F401
    generation,  # noqa: F401
    identity,  # noqa: F401
    jobs,  # noqa: F401
    knowledge,  # noqa: F401
    teaching,  # noqa: F401
)

target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    # Better Auth tables are versioned by its generated SQL, not ORM autogenerate.
    return type_ != "schema" or name in (None, "edu")


database_url = get_settings().database_url.get_secret_value()


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url, poolclass=pool.NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                include_schemas=True,
                include_name=include_name,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
