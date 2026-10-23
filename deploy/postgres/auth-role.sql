-- Run as database administrator BEFORE migration 0005. Never prints the secret.
\getenv auth_password DB_AUTH_PASSWORD
\getenv database_name POSTGRES_DB
BEGIN;
SELECT 'CREATE ROLE eduvia_auth_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '
  || quote_literal(:'auth_password')
WHERE NOT EXISTS(SELECT FROM pg_roles WHERE rolname='eduvia_auth_runtime')
\gexec
DO $$ BEGIN
  IF EXISTS(SELECT FROM pg_roles WHERE rolname='eduvia_auth_runtime' AND
    (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls)) THEN
    RAISE EXCEPTION 'Auth runtime has unsafe privileges';
  END IF;
  IF EXISTS(SELECT FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
    WHERE r.rolname='eduvia_auth_runtime') THEN
    RAISE EXCEPTION 'Auth runtime must not inherit other roles';
  END IF;
END $$;
GRANT CONNECT ON DATABASE :"database_name" TO eduvia_auth_runtime;
-- For an already-upgraded database, grant only its dedicated auth schema.
SELECT 'GRANT USAGE ON SCHEMA auth TO eduvia_auth_runtime; GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA auth TO eduvia_auth_runtime'
WHERE EXISTS(SELECT FROM pg_namespace WHERE nspname='auth')
\gexec
COMMIT;
