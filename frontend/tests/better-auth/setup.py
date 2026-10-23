"""Disposable PostgreSQL only; never imports local application secrets."""
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

url = os.environ["AUTH_TEST_DATABASE_URL"]
assert url.rsplit("/", 1)[-1].endswith("_test")
engine = create_engine(url)
with engine.begin() as db:
    db.execute(text("DROP SCHEMA IF EXISTS auth CASCADE; DROP SCHEMA IF EXISTS edu CASCADE; DROP TABLE IF EXISTS public.alembic_version"))
    db.execute(text("""DO $$ BEGIN
      IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='eduvia_auth_runtime') THEN
        CREATE ROLE eduvia_auth_runtime LOGIN PASSWORD 'auth_runtime_test_only' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
      END IF;
      IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='eduvia_runtime') THEN
        CREATE ROLE eduvia_runtime LOGIN PASSWORD 'runtime_test_only' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
      END IF;
    END $$;
    GRANT CONNECT ON DATABASE eduvia_auth_test TO eduvia_runtime,eduvia_auth_runtime;
    """))
os.environ["DATABASE_URL"] = url
command.upgrade(Config("alembic.ini"), "head")
with engine.begin() as db:
    db.execute(text("GRANT USAGE ON SCHEMA edu TO eduvia_runtime"))
engine.dispose()
