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
with engine.begin() as db:
    db.execute(text("""INSERT INTO edu.users(id,provider_issuer,provider_sub,email,display_name)
      VALUES('11111111-1111-4111-8111-111111111111','http://localhost:9101/','auth0|migration@example.test','migration@example.test','Legacy Teacher');
      INSERT INTO edu.user_identities(issuer,subject,user_id) VALUES('http://localhost:9101/','auth0|migration@example.test','11111111-1111-4111-8111-111111111111');
      INSERT INTO edu.workspaces(id,name,slug,workspace_type,personal_owner_user_id) VALUES('22222222-2222-4222-8222-222222222222','Existing workspace','existing-workspace','personal','11111111-1111-4111-8111-111111111111');
      INSERT INTO edu.workspace_members(workspace_id,user_id,role,status) VALUES('22222222-2222-4222-8222-222222222222','11111111-1111-4111-8111-111111111111','owner','active');
    """))
engine.dispose()
