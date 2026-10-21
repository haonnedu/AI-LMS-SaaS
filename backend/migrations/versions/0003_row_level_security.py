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
    # 1. Enable RLS on workspaces and workspace_members
    op.execute("ALTER TABLE edu.workspaces ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE edu.workspaces FORCE ROW LEVEL SECURITY")

    op.execute("ALTER TABLE edu.workspace_members ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE edu.workspace_members FORCE ROW LEVEL SECURITY")

    # 2. Policy for workspaces:
    # Restrict runtime access to workspaces where the user is an active member.
    op.execute(
        """
        CREATE POLICY workspace_membership_policy ON edu.workspaces
        AS RESTRICTIVE
        FOR ALL
        USING (
            current_setting('edu.current_workspace_id', true) IS NOT NULL
            AND current_setting('edu.current_workspace_id', true) != ''
            AND id::text = current_setting('edu.current_workspace_id', true)
            AND EXISTS (
                SELECT 1 FROM edu.workspace_members wm
                WHERE wm.workspace_id = edu.workspaces.id
                  AND wm.user_id::text = current_setting('edu.current_user_id', true)
                  AND wm.status = 'active'
            )
        )
        WITH CHECK (
            current_setting('edu.current_workspace_id', true) IS NOT NULL
            AND current_setting('edu.current_workspace_id', true) != ''
            AND id::text = current_setting('edu.current_workspace_id', true)
        )
        """
    )

    # 3. Policy for workspace_members:
    # Members can view memberships within their active workspace context.
    op.execute(
        """
        CREATE POLICY workspace_members_policy ON edu.workspace_members
        AS RESTRICTIVE
        FOR ALL
        USING (
            current_setting('edu.current_workspace_id', true) IS NOT NULL
            AND current_setting('edu.current_workspace_id', true) != ''
            AND workspace_id::text = current_setting('edu.current_workspace_id', true)
            AND EXISTS (
                SELECT 1 FROM edu.workspace_members wm_inner
                WHERE wm_inner.workspace_id = edu.workspace_members.workspace_id
                  AND wm_inner.user_id::text = current_setting('edu.current_user_id', true)
                  AND wm_inner.status = 'active'
            )
        )
        WITH CHECK (
            current_setting('edu.current_workspace_id', true) IS NOT NULL
            AND current_setting('edu.current_workspace_id', true) != ''
            AND workspace_id::text = current_setting('edu.current_workspace_id', true)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS workspace_members_policy ON edu.workspace_members")
    op.execute("DROP POLICY IF EXISTS workspace_membership_policy ON edu.workspaces")
    op.execute("ALTER TABLE edu.workspace_members DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE edu.workspaces DISABLE ROW LEVEL SECURITY")
