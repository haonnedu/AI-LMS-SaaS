"""Lean M2: durable jobs, usage ledger with a monthly cap, and private document storage.

All tables are tenant-scoped with ENABLE + FORCE RLS. The worker uses the same restricted
runtime role: it resolves a job's persisted actor through the narrow SECURITY DEFINER
``edu.job_actor`` helper, then sets transaction-local context like the API does.
"""

from alembic import op

revision = "0009_jobs_storage"
down_revision = "0008_classes"
branch_labels = None
depends_on = None

TENANT_TABLES = ("background_jobs", "usage_events", "workspace_quotas", "documents")

TENANT_PREDICATE = (
    "workspace_id::text = current_setting('edu.current_workspace_id', true) "
    "AND edu.can_read_workspace(workspace_id)"
)


def upgrade():
    op.execute("""
    CREATE TABLE edu.background_jobs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      requested_by_user_id uuid NOT NULL REFERENCES edu.users(id),
      kind text NOT NULL CHECK (length(kind) BETWEEN 1 AND 64),
      status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
      idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
      request_hash text NOT NULL,
      attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
      max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
      cancel_requested boolean NOT NULL DEFAULT false,
      lease_expires_at timestamptz,
      input jsonb NOT NULL DEFAULT '{}'::jsonb,
      result jsonb,
      error_code text,
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      started_at timestamptz,
      finished_at timestamptz,
      updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CONSTRAINT uq_background_jobs_idempotency
        UNIQUE (workspace_id, requested_by_user_id, idempotency_key),
      CONSTRAINT uq_background_jobs_workspace_id UNIQUE (workspace_id, id)
    );
    CREATE INDEX ix_background_jobs_workspace_status ON edu.background_jobs(workspace_id, status);
    CREATE INDEX ix_background_jobs_status_lease ON edu.background_jobs(status, lease_expires_at);
    CREATE INDEX ix_background_jobs_workspace_created
      ON edu.background_jobs(workspace_id, created_at);

    CREATE TABLE edu.usage_events (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      job_id uuid,
      kind text NOT NULL CHECK (length(kind) BETWEEN 1 AND 64),
      units integer NOT NULL CHECK (units >= 0 OR kind = 'release'),
      unit_type text NOT NULL CHECK (length(unit_type) BETWEEN 1 AND 32),
      provider_cost_minor bigint CHECK (provider_cost_minor IS NULL OR provider_cost_minor >= 0),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CONSTRAINT fk_usage_events_job FOREIGN KEY (workspace_id, job_id)
        REFERENCES edu.background_jobs(workspace_id, id)
    );
    CREATE INDEX ix_usage_events_workspace_created ON edu.usage_events(workspace_id, created_at);

    CREATE TABLE edu.workspace_quotas (
      workspace_id uuid PRIMARY KEY REFERENCES edu.workspaces(id),
      month_cap_units integer NOT NULL DEFAULT 1000 CHECK (month_cap_units >= 0),
      period_start date NOT NULL DEFAULT date_trunc('month', clock_timestamp())::date,
      updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );

    CREATE TABLE edu.documents (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      owner_user_id uuid NOT NULL REFERENCES edu.users(id),
      file_name text NOT NULL CHECK (length(file_name) BETWEEN 1 AND 255),
      mime_type text NOT NULL,
      size_bytes bigint NOT NULL CHECK (size_bytes > 0),
      sha256 bytea NOT NULL CHECK (octet_length(sha256) = 32),
      object_key text NOT NULL UNIQUE,
      status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','uploaded','quarantined','deleted')),
      rights_attested boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      deleted_at timestamptz,
      CONSTRAINT ck_documents_object_key_scope
        CHECK (object_key = 'ws/' || workspace_id::text || '/doc/' || id::text),
      CONSTRAINT ck_documents_deleted CHECK ((status = 'deleted') = (deleted_at IS NOT NULL))
    );
    CREATE INDEX ix_documents_workspace_status ON edu.documents(workspace_id, status);
    CREATE INDEX ix_documents_workspace_created ON edu.documents(workspace_id, created_at);
    """)

    # Every workspace gets exactly one quota row: backfill existing ones (RLS on workspaces is
    # relaxed for the migration owner only inside this transaction) and add a trigger for new.
    op.execute("""
    ALTER TABLE edu.workspaces NO FORCE ROW LEVEL SECURITY;
    INSERT INTO edu.workspace_quotas(workspace_id) SELECT id FROM edu.workspaces
      ON CONFLICT DO NOTHING;
    ALTER TABLE edu.workspaces FORCE ROW LEVEL SECURITY;
    """)

    for table in TENANT_TABLES:
        op.execute(f"""
        ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_tenant ON edu.{table} FOR ALL
          USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        """)

    op.execute("""
    GRANT CREATE ON SCHEMA edu TO eduvia_identity_owner;
    GRANT SELECT ON edu.background_jobs TO eduvia_identity_owner;
    GRANT SELECT, INSERT ON edu.workspace_quotas TO eduvia_identity_owner;
    CREATE POLICY job_actor_resolution ON edu.background_jobs FOR SELECT
      TO eduvia_identity_owner USING (true);
    CREATE POLICY quota_provisioning_select ON edu.workspace_quotas FOR SELECT
      TO eduvia_identity_owner USING (true);
    CREATE POLICY quota_provisioning_insert ON edu.workspace_quotas FOR INSERT
      TO eduvia_identity_owner WITH CHECK (true);

    -- Worker messages carry only a job ID; resolve the persisted actor narrowly.
    CREATE FUNCTION edu.job_actor(target uuid)
      RETURNS TABLE(workspace_id uuid, user_id uuid, issuer text, subject text)
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
        SELECT j.workspace_id, u.id, u.provider_issuer::text, u.provider_sub::text
        FROM edu.background_jobs j JOIN edu.users u ON u.id = j.requested_by_user_id
        WHERE j.id = target AND u.is_active
      $$;
    ALTER FUNCTION edu.job_actor(uuid) OWNER TO eduvia_identity_owner;

    -- Cross-tenant sweeper returns IDs only; each job is then processed under its own context.
    CREATE FUNCTION edu.overdue_job_ids(p_now timestamptz, p_queued_before timestamptz,
        p_limit integer)
      RETURNS SETOF uuid
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
        SELECT id FROM edu.background_jobs
        WHERE (status = 'running' AND lease_expires_at < p_now)
           OR (status = 'queued' AND updated_at < p_queued_before)
        ORDER BY updated_at
        LIMIT least(greatest(p_limit, 1), 500)
      $$;
    ALTER FUNCTION edu.overdue_job_ids(timestamptz, timestamptz, integer)
      OWNER TO eduvia_identity_owner;

    CREATE FUNCTION edu.provision_workspace_quota() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
      BEGIN
        INSERT INTO edu.workspace_quotas(workspace_id) VALUES (NEW.id) ON CONFLICT DO NOTHING;
        RETURN NEW;
      END $$;
    ALTER FUNCTION edu.provision_workspace_quota() OWNER TO eduvia_identity_owner;
    CREATE TRIGGER workspace_quota_provisioning AFTER INSERT ON edu.workspaces
      FOR EACH ROW EXECUTE FUNCTION edu.provision_workspace_quota();

    REVOKE ALL ON FUNCTION edu.job_actor(uuid),
      edu.overdue_job_ids(timestamptz, timestamptz, integer),
      edu.provision_workspace_quota() FROM PUBLIC;
    REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner;

    DO $$ BEGIN
      IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduvia_runtime') THEN
        -- Default privileges grant DELETE; replace them with the exact lean set.
        REVOKE ALL ON edu.background_jobs, edu.usage_events, edu.workspace_quotas,
          edu.documents FROM eduvia_runtime;
        GRANT SELECT, INSERT, UPDATE ON edu.background_jobs, edu.documents TO eduvia_runtime;
        -- usage_events is append-only for the runtime role.
        GRANT SELECT, INSERT ON edu.usage_events TO eduvia_runtime;
        -- SELECT ... FOR UPDATE needs UPDATE on one column; the cap itself stays read-only.
        GRANT SELECT, UPDATE (updated_at) ON edu.workspace_quotas TO eduvia_runtime;
        GRANT EXECUTE ON FUNCTION edu.job_actor(uuid),
          edu.overdue_job_ids(timestamptz, timestamptz, integer) TO eduvia_runtime;
      END IF;
    END $$;
    """)


def downgrade():
    raise RuntimeError("Jobs/storage migration is forward-only; restore a reviewed backup instead")
