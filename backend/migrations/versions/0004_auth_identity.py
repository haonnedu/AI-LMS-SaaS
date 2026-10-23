"""Issuer-scoped identity and least-privilege bootstrap.

Existing identities require an explicit -x identity_map=/path/map.json mapping
from user UUID to issuer. Existing personal workspaces require exactly one owner.
"""

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import context, op

revision = "0004_auth_identity"
down_revision = "0003_row_level_security"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # Role creation is an administrator prerequisite on a non-superuser migrator.
    op.execute("""
    DO $$ BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='eduvia_identity_owner') THEN
        CREATE ROLE eduvia_identity_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
      END IF;
    END $$;
    GRANT USAGE ON SCHEMA edu TO eduvia_identity_owner;
    GRANT CREATE ON SCHEMA edu TO eduvia_identity_owner;
    ALTER TABLE edu.users ADD COLUMN provider_issuer varchar(512);
    """)
    existing = list(bind.execute(sa.text("SELECT id FROM edu.users")))
    mapping_path = context.get_x_argument(as_dictionary=True).get("identity_map")
    mapping = json.loads(Path(mapping_path).read_text()) if mapping_path else {}
    for row in existing:
        issuer = mapping.get(str(row.id))
        if not isinstance(issuer, str) or not issuer.startswith("https://"):
            raise RuntimeError("Existing users need an explicit UUID-to-issuer identity_map")
        bind.execute(
            sa.text("UPDATE edu.users SET provider_issuer=:issuer WHERE id=:id"),
            {"issuer": issuer, "id": row.id},
        )
    op.execute("""
    ALTER TABLE edu.users ALTER COLUMN provider_issuer SET NOT NULL;
    ALTER TABLE edu.users DROP CONSTRAINT users_provider_sub_key;
    ALTER TABLE edu.users DROP CONSTRAINT users_email_key;
    ALTER TABLE edu.users ADD CONSTRAINT uq_user_identity UNIQUE(provider_issuer,provider_sub);
    ALTER TABLE edu.workspaces ADD COLUMN personal_owner_user_id uuid REFERENCES edu.users(id);
    -- Migration owner can inspect existing data during this transaction only.
    ALTER TABLE edu.workspaces NO FORCE ROW LEVEL SECURITY;
    DO $$ BEGIN
      IF EXISTS (SELECT w.id FROM edu.workspaces w LEFT JOIN edu.workspace_members m
        ON m.workspace_id=w.id AND m.role='owner'
        WHERE w.workspace_type='personal' GROUP BY w.id HAVING count(m.id)<>1) THEN
        RAISE EXCEPTION 'Existing personal workspaces require exactly one explicit owner';
      END IF;
    END $$;
    UPDATE edu.workspaces w SET personal_owner_user_id=m.user_id FROM edu.workspace_members m
      WHERE w.id=m.workspace_id AND w.workspace_type='personal' AND m.role='owner';
    ALTER TABLE edu.workspaces ADD CONSTRAINT uq_personal_owner UNIQUE(personal_owner_user_id);
    ALTER TABLE edu.workspaces ADD CONSTRAINT ck_personal_owner
      CHECK ((workspace_type='personal') = (personal_owner_user_id IS NOT NULL));
    DROP POLICY workspace_membership_policy ON edu.workspaces;
    DROP POLICY workspace_members_policy ON edu.workspace_members;
    DROP FUNCTION edu.is_active_member();
    ALTER TABLE edu.users ENABLE ROW LEVEL SECURITY;
    ALTER TABLE edu.users FORCE ROW LEVEL SECURITY;
    ALTER TABLE edu.workspaces FORCE ROW LEVEL SECURITY;
    ALTER TABLE edu.workspace_members FORCE ROW LEVEL SECURITY;
    -- Privileged functions use a NOLOGIN role, not a runtime bypass or table owner exemption.
    GRANT SELECT, INSERT, UPDATE ON edu.users,edu.workspaces,edu.workspace_members TO
      eduvia_identity_owner;
    CREATE POLICY identity_function_users ON edu.users TO eduvia_identity_owner USING(true) WITH
      CHECK(true);
    CREATE POLICY identity_function_workspaces ON edu.workspaces TO eduvia_identity_owner
      USING(true) WITH CHECK(true);
    CREATE POLICY identity_function_members ON edu.workspace_members TO eduvia_identity_owner
      USING(true) WITH CHECK(true);
    CREATE POLICY own_identity ON edu.users FOR SELECT USING (
      provider_issuer=current_setting('edu.issuer',true) AND
      provider_sub=current_setting('edu.subject',true));
    CREATE FUNCTION edu.actor_id() RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER
      SET search_path=pg_catalog,edu AS $$
        SELECT id FROM edu.users WHERE provider_issuer=current_setting('edu.issuer',true)
          AND provider_sub=current_setting('edu.subject',true) AND is_active
      $$;
    ALTER FUNCTION edu.actor_id() OWNER TO eduvia_identity_owner;
    CREATE FUNCTION edu.can_read_workspace(target uuid) RETURNS boolean LANGUAGE sql STABLE
      SECURITY DEFINER
      SET search_path=pg_catalog,edu AS $$
        SELECT EXISTS(SELECT 1 FROM edu.workspace_members m JOIN edu.workspaces w ON
      w.id=m.workspace_id
          WHERE m.user_id=edu.actor_id() AND m.workspace_id=target AND m.status='active' AND
      w.is_active)
      $$;
    ALTER FUNCTION edu.can_read_workspace(uuid) OWNER TO eduvia_identity_owner;
    CREATE POLICY own_membership ON edu.workspace_members FOR SELECT USING (
      user_id=edu.actor_id() AND status='active' AND edu.can_read_workspace(workspace_id));
    CREATE POLICY readable_workspace ON edu.workspaces FOR SELECT USING
      (edu.can_read_workspace(id));
    CREATE FUNCTION edu.bootstrap_identity(p_email text,p_name text) RETURNS uuid
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
    DECLARE actor uuid; ws uuid; active boolean;
      issuer text := nullif(current_setting('edu.issuer',true),'');
      subject text := nullif(current_setting('edu.subject',true),'');
    BEGIN
      IF issuer IS NULL OR subject IS NULL OR p_email IS NULL OR p_email='' THEN
        RAISE EXCEPTION 'Missing verified identity' USING ERRCODE='28000';
      END IF;
      INSERT INTO edu.users(provider_issuer,provider_sub,email,display_name)
        VALUES(issuer,subject,p_email,p_name)
        ON CONFLICT(provider_issuer,provider_sub) DO UPDATE
          SET email=excluded.email,display_name=excluded.display_name,updated_at=clock_timestamp()
          WHERE edu.users.is_active
        RETURNING id,is_active INTO actor,active;
      IF actor IS NULL OR NOT active THEN
        RAISE EXCEPTION 'Account disabled' USING ERRCODE='28000';
      END IF;
      -- User upsert locks the identity row, serializing first-workspace creation.
      SELECT id INTO ws FROM edu.workspaces WHERE personal_owner_user_id=actor;
      IF ws IS NULL THEN
        INSERT INTO edu.workspaces(name,slug,workspace_type,personal_owner_user_id)
          VALUES('Không gian cá nhân','personal-'||actor::text,'personal',actor) RETURNING id
      INTO ws;
        INSERT INTO edu.workspace_members(workspace_id,user_id,role,status)
      VALUES(ws,actor,'owner','active');
      END IF;
      -- Never resurrect an archived workspace or a revoked membership on login.
      RETURN actor;
    END $$;
    ALTER FUNCTION edu.bootstrap_identity(text,text) OWNER TO eduvia_identity_owner;
    REVOKE ALL ON FUNCTION
      edu.actor_id(),edu.can_read_workspace(uuid),edu.bootstrap_identity(text,text) FROM PUBLIC;
    REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner;
    DO $$ BEGIN
      IF EXISTS(SELECT FROM pg_roles WHERE rolname='eduvia_runtime') THEN
        REVOKE ALL ON edu.users,edu.workspaces,edu.workspace_members FROM eduvia_runtime;
        GRANT SELECT ON edu.users,edu.workspaces,edu.workspace_members TO eduvia_runtime;
        GRANT EXECUTE ON FUNCTION
      edu.actor_id(),edu.can_read_workspace(uuid),edu.bootstrap_identity(text,text) TO
      eduvia_runtime;
      END IF;
    END $$;
    """)


def downgrade():
    raise RuntimeError("Identity migration is forward-only; restore a reviewed backup instead")
