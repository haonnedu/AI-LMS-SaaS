-- First initialization only, as the cluster administrator. Not a rotation script.
-- psql getenv avoids placing credentials in command-line arguments.
\getenv migrator_password DB_MIGRATOR_PASSWORD
\getenv runtime_password DB_RUNTIME_PASSWORD
BEGIN;
CREATE ROLE eduvia_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'migrator_password';
CREATE ROLE eduvia_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'runtime_password';
REVOKE ALL ON DATABASE eduvia FROM PUBLIC;
GRANT CONNECT ON DATABASE eduvia TO eduvia_migrator, eduvia_runtime;
-- Existing migration issues CREATE SCHEMA IF NOT EXISTS; allow schema DDL only
-- for the migration identity, never the runtime identity.
GRANT CREATE ON DATABASE eduvia TO eduvia_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
-- Alembic's version table lives in public with the current migration env.
GRANT USAGE, CREATE ON SCHEMA public TO eduvia_migrator;
GRANT USAGE ON SCHEMA public TO eduvia_runtime;
-- vector is not a trusted extension: install it before non-superuser Alembic runs.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE SCHEMA edu AUTHORIZATION eduvia_migrator;
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
