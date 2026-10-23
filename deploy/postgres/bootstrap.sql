-- First initialization or adoption of an empty 0001 bootstrap, as administrator.
-- Not a credential rotation or populated-schema ownership transfer script.
-- psql getenv avoids placing credentials in command-line arguments.
\getenv migrator_password DB_MIGRATOR_PASSWORD
\getenv runtime_password DB_RUNTIME_PASSWORD
\getenv database_name POSTGRES_DB
BEGIN;
-- An older local volume may already contain the empty 0001 namespace and the
-- Alembic version table, owned by its original administrator. Adopt only that
-- exact baseline; never transfer ownership of existing product data implicitly.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'edu'
  ) OR EXISTS (
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'edu'
  ) OR EXISTS (
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'edu'
  ) THEN
    RAISE EXCEPTION 'Bootstrap requires an empty edu schema; populated databases need a reviewed migration';
  END IF;
  IF to_regclass('public.alembic_version') IS NOT NULL THEN
    IF (SELECT count(*) FROM public.alembic_version) <> 1 OR NOT EXISTS (
      SELECT 1 FROM public.alembic_version WHERE version_num = '0001_bootstrap'
    ) THEN
      RAISE EXCEPTION 'Bootstrap adoption only supports revision 0001_bootstrap';
    END IF;
  END IF;
END $$;
CREATE ROLE eduvia_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'migrator_password';
CREATE ROLE eduvia_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'runtime_password';
CREATE ROLE eduvia_identity_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT eduvia_identity_owner TO eduvia_migrator;
REVOKE ALL ON DATABASE :"database_name" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"database_name" TO eduvia_migrator, eduvia_runtime;
-- Existing migration issues CREATE SCHEMA IF NOT EXISTS; allow schema DDL only
-- for the migration identity, never the runtime identity.
GRANT CREATE ON DATABASE :"database_name" TO eduvia_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
-- Alembic's version table lives in public with the current migration env.
GRANT USAGE, CREATE ON SCHEMA public TO eduvia_migrator;
GRANT USAGE ON SCHEMA public TO eduvia_runtime;
-- vector is not a trusted extension: install it before non-superuser Alembic runs.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE SCHEMA IF NOT EXISTS edu AUTHORIZATION eduvia_migrator;
ALTER SCHEMA edu OWNER TO eduvia_migrator;
DO $$
BEGIN
  IF to_regclass('public.alembic_version') IS NOT NULL THEN
    ALTER TABLE public.alembic_version OWNER TO eduvia_migrator;
  END IF;
END $$;
REVOKE ALL ON SCHEMA edu FROM PUBLIC;
GRANT USAGE ON SCHEMA edu TO eduvia_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE eduvia_migrator IN SCHEMA edu
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO eduvia_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE eduvia_migrator IN SCHEMA edu
  GRANT USAGE, SELECT ON SEQUENCES TO eduvia_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE eduvia_migrator IN SCHEMA edu
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
COMMIT;
-- Runtime has no schema CREATE, table ownership, role membership or BYPASSRLS.
-- This is privilege separation, NOT row-level security or tenant isolation.
