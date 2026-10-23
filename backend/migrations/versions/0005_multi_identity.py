"""Preserve Eduvia IDs while introducing multiple login identities and auth storage."""

from pathlib import Path

from alembic import op

revision = "0005_multi_identity"
down_revision = "0004_auth_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE edu.user_identities (
      issuer varchar(512) NOT NULL, subject varchar(255) NOT NULL,
      user_id uuid NOT NULL REFERENCES edu.users(id),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY(issuer,subject));
    ALTER TABLE edu.users NO FORCE ROW LEVEL SECURITY;
    INSERT INTO edu.user_identities(issuer,subject,user_id)
      SELECT provider_issuer,provider_sub,id FROM edu.users;
    ALTER TABLE edu.users FORCE ROW LEVEL SECURITY;
    ALTER TABLE edu.user_identities ENABLE ROW LEVEL SECURITY;
    ALTER TABLE edu.user_identities FORCE ROW LEVEL SECURITY;
    GRANT SELECT,INSERT ON edu.user_identities TO eduvia_identity_owner;
    CREATE POLICY identity_function_aliases ON edu.user_identities TO eduvia_identity_owner
      USING(true) WITH CHECK(true);
    CREATE POLICY own_alias ON edu.user_identities FOR SELECT USING (
      issuer=current_setting('edu.issuer',true) AND subject=current_setting('edu.subject',true));
    CREATE OR REPLACE FUNCTION edu.actor_id() RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER
      SET search_path=pg_catalog,edu AS $$
        SELECT u.id FROM edu.users u JOIN edu.user_identities i ON i.user_id=u.id
        WHERE i.issuer=current_setting('edu.issuer',true)
          AND i.subject=current_setting('edu.subject',true) AND u.is_active
      $$;
    DROP POLICY own_identity ON edu.users;
    CREATE POLICY own_identity ON edu.users FOR SELECT USING (id IN (
      SELECT user_id FROM edu.user_identities WHERE issuer=current_setting('edu.issuer',true)
        AND subject=current_setting('edu.subject',true)));
    CREATE OR REPLACE FUNCTION edu.bootstrap_identity(p_email text,p_name text) RETURNS uuid
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
    DECLARE actor uuid; ws uuid;
      identity_issuer text := nullif(current_setting('edu.issuer',true),'');
      identity_subject text := nullif(current_setting('edu.subject',true),'');
    BEGIN
      IF identity_issuer IS NULL OR identity_subject IS NULL OR nullif(p_email,'') IS NULL THEN
        RAISE EXCEPTION 'Missing verified identity' USING ERRCODE='28000';
      END IF;
      PERFORM pg_advisory_xact_lock(hashtextextended(identity_issuer||chr(31)||identity_subject,0));
      SELECT user_id INTO actor FROM edu.user_identities
        WHERE user_identities.issuer=identity_issuer AND user_identities.subject=identity_subject;
      IF actor IS NULL THEN
        INSERT INTO edu.users(provider_issuer,provider_sub,email,display_name)
          VALUES(identity_issuer,identity_subject,p_email,p_name) RETURNING id INTO actor;
        INSERT INTO edu.user_identities
          VALUES(identity_issuer,identity_subject,actor,clock_timestamp());
      END IF;
      PERFORM 1 FROM edu.users WHERE id=actor AND is_active FOR UPDATE;
      IF NOT FOUND THEN RAISE EXCEPTION 'Account disabled' USING ERRCODE='28000'; END IF;
      UPDATE edu.users SET email=p_email,display_name=p_name,updated_at=clock_timestamp()
        WHERE id=actor;
      SELECT id INTO ws FROM edu.workspaces WHERE personal_owner_user_id=actor;
      IF ws IS NULL THEN
        INSERT INTO edu.workspaces(name,slug,workspace_type,personal_owner_user_id)
          VALUES('Không gian cá nhân','personal-'||actor::text,'personal',actor)
          RETURNING id INTO ws;
        INSERT INTO edu.workspace_members(workspace_id,user_id,role,status)
          VALUES(ws,actor,'owner','active');
      END IF;
      RETURN actor;
    END $$;
    DO $$ BEGIN
      IF EXISTS(SELECT FROM pg_roles WHERE rolname='eduvia_runtime') THEN
        REVOKE ALL ON edu.user_identities FROM eduvia_runtime;
        GRANT SELECT ON edu.user_identities TO eduvia_runtime;
      END IF;
    END $$;
    CREATE SCHEMA auth;
    REVOKE ALL ON SCHEMA auth FROM PUBLIC;
    """)
    op.execute((Path(__file__).parent.parent / "sql" / "better-auth-1.7.12.sql").read_text())
    # A DBA creates the LOGIN role/password out of band. No credentials in migrations.
    op.execute("""
    DO $$ BEGIN
      IF EXISTS(SELECT FROM pg_roles WHERE rolname='eduvia_auth_runtime') THEN
        GRANT USAGE ON SCHEMA auth TO eduvia_auth_runtime;
        GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA auth TO eduvia_auth_runtime;
      END IF;
    END $$;
    """)


def downgrade():
    raise RuntimeError("Identity migration is forward-only; restore a reviewed backup instead")
