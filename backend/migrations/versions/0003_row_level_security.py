"""Row Level Security (RLS) migration.

Revision ID: 0003_row_level_security
Revises: 0002_identity_and_workspaces
"""

from alembic import op

revision = "0003_row_level_security"
down_revision = "0002_identity_and_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Membership predicate as a SECURITY DEFINER helper.
    # A policy on workspace_members cannot query workspace_members directly: PostgreSQL
    # re-applies the same policy and aborts with "infinite recursion detected in policy".
    # Running the lookup as the defining role (migrator) reads the table once, outside the
    # policy, so the predicate works. workspace_members is deliberately ENABLEd but not
    # FORCEd: that exemption is exactly what lets this function read it, while every other
    # role is still filtered. Tenant isolation for those roles does not depend on it.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION edu.is_active_member() RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, edu
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM edu.workspace_members m
                WHERE m.workspace_id::text
                      = current_setting('edu.current_workspace_id', true)
                  AND m.user_id::text
                      = current_setting('edu.current_user_id', true)
                  AND m.status = 'active'
            )
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION edu.is_active_member() FROM PUBLIC")
    # Only grant EXECUTE if the role exists (in local dev/tests without bootstrap role, skip)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eduvia_runtime') THEN
                GRANT EXECUTE ON FUNCTION edu.is_active_member() TO eduvia_runtime;
            END IF;
        END $$;
        """
    )

    # 2. Workspaces: FORCEd, so even the owning role is filtered. A caller sees only the
    # workspace named by the verified transaction-local context, and only while its own
    # membership there is active.
    op.execute("ALTER TABLE edu.workspaces ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE edu.workspaces FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY workspace_membership_policy ON edu.workspaces
        FOR ALL
        USING (
            current_setting('edu.current_workspace_id', true) <> ''
            AND id::text = current_setting('edu.current_workspace_id', true)
            AND edu.is_active_member()
        )
        WITH CHECK (
            current_setting('edu.current_workspace_id', true) <> ''
            AND id::text = current_setting('edu.current_workspace_id', true)
            AND edu.is_active_member()
        )
        """
    )

    # 3. Memberships: readable and writable only inside the current workspace and only by
    # an active member of it. ENABLE without FORCE (see step 1).
    op.execute("ALTER TABLE edu.workspace_members ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY workspace_members_policy ON edu.workspace_members
        FOR ALL
        USING (
            current_setting('edu.current_workspace_id', true) <> ''
            AND workspace_id::text = current_setting('edu.current_workspace_id', true)
            AND edu.is_active_member()
        )
        WITH CHECK (
            current_setting('edu.current_workspace_id', true) <> ''
            AND workspace_id::text = current_setting('edu.current_workspace_id', true)
            AND edu.is_active_member()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS workspace_members_policy ON edu.workspace_members")
    op.execute("DROP POLICY IF EXISTS workspace_membership_policy ON edu.workspaces")
    op.execute("ALTER TABLE edu.workspace_members DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE edu.workspaces DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS edu.is_active_member()")
