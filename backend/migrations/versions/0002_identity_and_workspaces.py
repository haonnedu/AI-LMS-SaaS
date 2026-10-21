"""Identity and workspaces migration.

Revision ID: 0002_identity_and_workspaces
Revises: 0001_bootstrap
"""

from alembic import op

revision = "0002_identity_and_workspaces"
down_revision = "0001_bootstrap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Users table (Global user identity)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS edu.users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email VARCHAR(255) NOT NULL UNIQUE,
            provider_sub VARCHAR(255) NOT NULL UNIQUE,
            display_name VARCHAR(255),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        )
        """
    )

    # 2. Workspaces table (Personal or School workspaces)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS edu.workspaces (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) NOT NULL,
            slug VARCHAR(255) NOT NULL UNIQUE,
            workspace_type VARCHAR(50) NOT NULL DEFAULT 'personal', -- personal | school
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        )
        """
    )

    # 3. Workspace members table (Membership & roles)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS edu.workspace_members (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id UUID NOT NULL REFERENCES edu.workspaces(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES edu.users(id) ON DELETE CASCADE,
            role VARCHAR(50) NOT NULL DEFAULT 'teacher', -- owner, admin, teacher, student
            status VARCHAR(50) NOT NULL DEFAULT 'active', -- active, suspended, departed
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT uq_workspace_user UNIQUE (workspace_id, user_id)
        )
        """
    )

    # Indexes for performance
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspace_members_user_id ON edu.workspace_members(user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace_id "
        "ON edu.workspace_members(workspace_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS edu.workspace_members CASCADE")
    op.execute("DROP TABLE IF EXISTS edu.workspaces CASCADE")
    op.execute("DROP TABLE IF EXISTS edu.users CASCADE")
