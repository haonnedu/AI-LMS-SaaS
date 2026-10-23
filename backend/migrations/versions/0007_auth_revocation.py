"""Durable fail-closed session revocation for cross-store credential changes."""

from alembic import op

revision = "0007_auth_revocation"
down_revision = "0006_identity_transfer"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE auth.session_revocations (
      user_id text PRIMARY KEY REFERENCES auth."user"(id) ON DELETE CASCADE,
      revoked_before timestamptz NOT NULL);
    REVOKE ALL ON auth.session_revocations FROM PUBLIC;
    DO $$ BEGIN
      IF EXISTS(SELECT FROM pg_roles WHERE rolname='eduvia_auth_runtime') THEN
        GRANT SELECT,INSERT,UPDATE ON auth.session_revocations TO eduvia_auth_runtime;
      END IF;
    END $$;
    """)


def downgrade():
    raise RuntimeError("Auth migration is forward-only; restore a reviewed backup instead")
