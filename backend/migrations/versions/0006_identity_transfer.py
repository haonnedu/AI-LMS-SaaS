"""Restricted, audited identity transfer; no email-based account merging."""

from alembic import op

revision = "0006_identity_transfer"
down_revision = "0005_multi_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    GRANT CREATE ON SCHEMA edu TO eduvia_identity_owner;
    CREATE TABLE edu.identity_transfers (
      proof_id text PRIMARY KEY, user_id uuid NOT NULL REFERENCES edu.users(id),
      target_issuer text NOT NULL, target_subject text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT clock_timestamp());
    ALTER TABLE edu.identity_transfers ENABLE ROW LEVEL SECURITY;
    ALTER TABLE edu.identity_transfers FORCE ROW LEVEL SECURITY;
    GRANT SELECT,INSERT ON edu.identity_transfers TO eduvia_identity_owner;
    CREATE POLICY transfer_function ON edu.identity_transfers TO eduvia_identity_owner
      USING(true) WITH CHECK(true);
    CREATE FUNCTION edu.transfer_identity(source_issuer text,source_subject text,
      target_issuer text,target_subject text,proof_id text) RETURNS uuid
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
    #variable_conflict use_variable
    DECLARE actor uuid; target uuid; proof_owner uuid;
    BEGIN
      IF source_issuer=target_issuer OR nullif(proof_id,'') IS NULL THEN
        RAISE EXCEPTION 'Invalid migration' USING ERRCODE='22023';
      END IF;
      -- Serialize transfers and bootstrap of the destination identity.
      PERFORM pg_advisory_xact_lock(hashtextextended(target_issuer||chr(31)||target_subject,0));
      SELECT user_id INTO actor FROM edu.user_identities
        WHERE issuer=source_issuer AND subject=source_subject;
      PERFORM 1 FROM edu.users WHERE id=actor AND is_active FOR UPDATE;
      IF NOT FOUND THEN RAISE EXCEPTION 'Source unavailable' USING ERRCODE='28000'; END IF;
      SELECT user_id INTO target FROM edu.user_identities
        WHERE issuer=target_issuer AND subject=target_subject;
      IF target IS NOT NULL AND target<>actor THEN
        RAISE EXCEPTION 'Identity belongs to another user' USING ERRCODE='23505';
      END IF;
      INSERT INTO edu.identity_transfers
        VALUES(proof_id,actor,target_issuer,target_subject,clock_timestamp())
        ON CONFLICT DO NOTHING;
      SELECT t.user_id INTO proof_owner FROM edu.identity_transfers t
        WHERE t.proof_id=transfer_identity.proof_id
          AND t.target_issuer=transfer_identity.target_issuer
          AND t.target_subject=transfer_identity.target_subject;
      IF proof_owner IS DISTINCT FROM actor THEN
        RAISE EXCEPTION 'Proof replay' USING ERRCODE='23505';
      END IF;
      INSERT INTO edu.user_identities(issuer,subject,user_id)
        VALUES(target_issuer,target_subject,actor) ON CONFLICT DO NOTHING;
      RETURN actor;
    END $$;
    ALTER FUNCTION edu.transfer_identity(text,text,text,text,text) OWNER TO eduvia_identity_owner;
    REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner;
    REVOKE ALL ON FUNCTION edu.transfer_identity(text,text,text,text,text) FROM PUBLIC;
    DO $$ BEGIN
      IF EXISTS(SELECT FROM pg_roles WHERE rolname='eduvia_runtime') THEN
        REVOKE ALL ON edu.identity_transfers FROM eduvia_runtime;
        GRANT EXECUTE ON FUNCTION edu.transfer_identity(text,text,text,text,text) TO eduvia_runtime;
      END IF;
    END $$;
    """)


def downgrade():
    raise RuntimeError("Identity migration is forward-only; restore a reviewed backup instead")
