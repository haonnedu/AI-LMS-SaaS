"""Bootstrap namespace and vector extension without exposing tenant data.

Revision ID: 0001_bootstrap
Revises: None
"""

from alembic import op

revision = "0001_bootstrap"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.execute("CREATE SCHEMA IF NOT EXISTS edu")
    op.execute("REVOKE ALL ON SCHEMA edu FROM PUBLIC")


def downgrade() -> None:
    # RESTRICT prevents removing a namespace containing independently created data.
    # Keep vector: this database-wide extension may be used by another schema.
    op.execute("DROP SCHEMA IF EXISTS edu RESTRICT")
