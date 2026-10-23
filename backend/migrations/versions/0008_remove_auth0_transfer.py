"""Retire the account transfer gate; preserve identity and workspace tables."""

from alembic import op

revision = "0008_remove_auth0_transfer"
down_revision = "0007_auth_revocation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM edu.identity_transfers) THEN
        RAISE EXCEPTION 'Review and archive transfer receipts before retiring the gate';
      END IF;
    END $$;
    DROP FUNCTION edu.transfer_identity(text,text,text,text,text);
    DROP TABLE edu.identity_transfers;
    """)


def downgrade():
    raise RuntimeError("Auth cleanup is forward-only; restore a reviewed backup instead")
