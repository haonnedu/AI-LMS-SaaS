"""M4 AI-assisted half: generation provenance, immutable exam snapshots and export jobs
(AUTHR-03/04, BP-03/04, EXPORT-01).

* ``generation_jobs`` / ``generation_sources``: one row per AI draft job (1:1 with its
  ``background_jobs`` row) recording prompt version, provider/model, token usage and the exact
  chunks that were sent to the provider (rank, citation label, SHA-256 of the chunk text). No
  prompt text, student data or file names are stored. ``generation_sources.chunk_id`` is
  ``ON DELETE SET NULL``: purging a withdrawn document (``edu.purge_document_chunks``) must not be
  blocked by provenance, and the row keeps label/rank/hash as a tombstone ("withdrawn").
* ``exams`` / ``exam_versions`` / ``exam_items`` / ``exam_answer_keys``: a version is a snapshot
  (stem/choices/points copied from the bank, key copied through ``edu.question_key``). Items and
  keys can only be inserted into a ``draft`` version; once ``published_at`` is set the version,
  its items and its keys are frozen by BEFORE UPDATE/DELETE triggers (archival only flips the
  status). Publication is validated by ``edu.exam_version_publish_error`` inside the version
  trigger: >= 1 item, 3..5 choices, exactly one key per item naming one of its choices, points
  > 0 and sum(points) = total_points.
* ``exam_answer_keys`` mirrors ``question_keys``: the runtime role may INSERT only and has NO
  SELECT. Staff read keys through ``edu.exam_item_key`` (teacher roles) and explanations through
  ``edu.exam_item_explanation``; scoring reads ``edu.exam_keys_for_scoring`` which requires the
  workspace context, ``edu.can_read_workspace`` and a published version (no role check: the
  scoring worker runs as the job's actor).
* ``export_jobs``: exactly one source (content revision XOR exam version), server-chosen object
  key, ``queued -> succeeded|failed``.
"""

from alembic import op

revision = "0010_generation_exams"
down_revision = "0009_authoring"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "generation_jobs",
    "generation_sources",
    "exams",
    "exam_versions",
    "exam_items",
    "exam_answer_keys",
    "export_jobs",
)

TENANT_PREDICATE = (
    "workspace_id::text = current_setting('edu.current_workspace_id', true) "
    "AND edu.can_read_workspace(workspace_id)"
)

MAX_JSON_BYTES = 262144


def upgrade():
    op.execute(f"""
    CREATE TABLE edu.generation_jobs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      background_job_id uuid NOT NULL,
      requested_by_user_id uuid NOT NULL REFERENCES edu.users(id),
      purpose text NOT NULL CHECK (purpose IN ('lesson_plan','study_guide','questions')),
      input jsonb NOT NULL CHECK (
        jsonb_typeof(input) = 'object' AND octet_length(input::text) <= 65536
      ),
      prompt_version text NOT NULL CHECK (length(prompt_version) BETWEEN 1 AND 64),
      provider text NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
      model text NOT NULL CHECK (length(model) BETWEEN 1 AND 128),
      provider_request_id text
        CHECK (provider_request_id IS NULL OR length(provider_request_id) <= 128),
      output jsonb CHECK (output IS NULL OR octet_length(output::text) <= {MAX_JSON_BYTES}),
      validation_status text NOT NULL DEFAULT 'pending'
        CHECK (validation_status IN ('pending','valid','invalid','failed')),
      input_tokens bigint CHECK (input_tokens IS NULL OR input_tokens >= 0),
      output_tokens bigint CHECK (output_tokens IS NULL OR output_tokens >= 0),
      cost_minor bigint CHECK (cost_minor IS NULL OR cost_minor >= 0),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      finished_at timestamptz,
      CONSTRAINT uq_generation_jobs_background_job UNIQUE (background_job_id),
      CONSTRAINT uq_generation_jobs_workspace_id UNIQUE (workspace_id, id),
      CONSTRAINT fk_generation_jobs_background_job FOREIGN KEY (workspace_id, background_job_id)
        REFERENCES edu.background_jobs(workspace_id, id),
      CONSTRAINT ck_generation_jobs_finished CHECK (
        (validation_status = 'pending') = (finished_at IS NULL)
      )
    );
    CREATE INDEX ix_generation_jobs_listing
      ON edu.generation_jobs(workspace_id, created_at DESC, id DESC);

    CREATE TABLE edu.generation_sources (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      generation_job_id uuid NOT NULL,
      chunk_id uuid REFERENCES edu.document_chunks(id) ON DELETE SET NULL,
      citation_label text NOT NULL CHECK (length(citation_label) BETWEEN 1 AND 32),
      text_sha256 bytea NOT NULL CHECK (octet_length(text_sha256) = 32),
      rank integer NOT NULL CHECK (rank >= 1),
      CONSTRAINT uq_generation_sources_rank UNIQUE (generation_job_id, rank),
      CONSTRAINT uq_generation_sources_workspace_id UNIQUE (workspace_id, id),
      CONSTRAINT fk_generation_sources_job FOREIGN KEY (workspace_id, generation_job_id)
        REFERENCES edu.generation_jobs(workspace_id, id)
    );
    CREATE INDEX ix_generation_sources_chunk ON edu.generation_sources(chunk_id);

    CREATE TABLE edu.exams (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      title text NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
      blueprint_version_id uuid,
      status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
      created_by_user_id uuid NOT NULL REFERENCES edu.users(id),
      current_version_id uuid,
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CONSTRAINT uq_exams_workspace_id UNIQUE (workspace_id, id),
      CONSTRAINT fk_exams_blueprint_version FOREIGN KEY (workspace_id, blueprint_version_id)
        REFERENCES edu.blueprint_versions(workspace_id, id)
    );
    CREATE INDEX ix_exams_listing ON edu.exams(workspace_id, created_at DESC, id DESC);

    CREATE TABLE edu.exam_versions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      exam_id uuid NOT NULL,
      version_no integer NOT NULL CHECK (version_no > 0),
      status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
      total_points numeric(10,2) NOT NULL CHECK (total_points > 0),
      content_hash bytea CHECK (content_hash IS NULL OR octet_length(content_hash) = 32),
      blueprint_version_id uuid,
      published_at timestamptz,
      published_by_user_id uuid REFERENCES edu.users(id),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CONSTRAINT uq_exam_versions_number UNIQUE (exam_id, version_no),
      CONSTRAINT uq_exam_versions_workspace_id UNIQUE (workspace_id, id),
      CONSTRAINT uq_exam_versions_owner UNIQUE (workspace_id, exam_id, id),
      CONSTRAINT fk_exam_versions_exam FOREIGN KEY (workspace_id, exam_id)
        REFERENCES edu.exams(workspace_id, id),
      CONSTRAINT fk_exam_versions_blueprint_version FOREIGN KEY (workspace_id, blueprint_version_id)
        REFERENCES edu.blueprint_versions(workspace_id, id),
      CONSTRAINT ck_exam_versions_published CHECK (
        status <> 'published'
        OR (published_at IS NOT NULL AND published_by_user_id IS NOT NULL
            AND content_hash IS NOT NULL)
      )
    );

    ALTER TABLE edu.exams ADD CONSTRAINT fk_exams_current_version
      FOREIGN KEY (workspace_id, id, current_version_id)
      REFERENCES edu.exam_versions(workspace_id, exam_id, id)
      DEFERRABLE INITIALLY DEFERRED;

    CREATE TABLE edu.exam_items (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      exam_version_id uuid NOT NULL,
      position integer NOT NULL CHECK (position >= 1),
      item_type text NOT NULL DEFAULT 'single_choice' CHECK (item_type IN ('single_choice')),
      stem text NOT NULL CHECK (length(stem) BETWEEN 1 AND 10000),
      choices jsonb NOT NULL CHECK (
        jsonb_typeof(choices) = 'array' AND jsonb_array_length(choices) BETWEEN 3 AND 5
      ),
      points numeric(10,2) NOT NULL CHECK (points > 0),
      source_question_revision_id uuid,
      curriculum_unit_id uuid REFERENCES edu.curriculum_units(id),
      cognitive_level text CHECK (
        cognitive_level IS NULL
        OR cognitive_level IN ('remember','understand','apply','analyze')
      ),
      CONSTRAINT uq_exam_items_position UNIQUE (exam_version_id, position),
      CONSTRAINT uq_exam_items_workspace_id UNIQUE (workspace_id, id),
      CONSTRAINT uq_exam_items_version_owner UNIQUE (workspace_id, exam_version_id, id),
      CONSTRAINT fk_exam_items_version FOREIGN KEY (workspace_id, exam_version_id)
        REFERENCES edu.exam_versions(workspace_id, id),
      CONSTRAINT fk_exam_items_question_revision
        FOREIGN KEY (workspace_id, source_question_revision_id)
        REFERENCES edu.question_revisions(workspace_id, id)
    );

    CREATE TABLE edu.exam_answer_keys (
      exam_item_id uuid PRIMARY KEY,
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      exam_version_id uuid NOT NULL,
      correct_key char(1) NOT NULL CHECK (correct_key IN ('A','B','C','D','E')),
      explanation text CHECK (explanation IS NULL OR length(explanation) <= 10000),
      CONSTRAINT fk_exam_answer_keys_item FOREIGN KEY (workspace_id, exam_version_id, exam_item_id)
        REFERENCES edu.exam_items(workspace_id, exam_version_id, id),
      CONSTRAINT fk_exam_answer_keys_version FOREIGN KEY (workspace_id, exam_version_id)
        REFERENCES edu.exam_versions(workspace_id, id)
    );
    CREATE INDEX ix_exam_answer_keys_version
      ON edu.exam_answer_keys(workspace_id, exam_version_id);

    CREATE TABLE edu.export_jobs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      background_job_id uuid NOT NULL,
      content_revision_id uuid,
      exam_version_id uuid,
      format text NOT NULL CHECK (format IN ('docx','pdf')),
      audience text NOT NULL CHECK (audience IN ('teacher','student')),
      object_key text UNIQUE CHECK (object_key IS NULL OR length(object_key) BETWEEN 1 AND 512),
      status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','succeeded','failed')),
      error_code text CHECK (error_code IS NULL OR length(error_code) BETWEEN 1 AND 64),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      finished_at timestamptz,
      CONSTRAINT uq_export_jobs_background_job UNIQUE (background_job_id),
      CONSTRAINT uq_export_jobs_workspace_id UNIQUE (workspace_id, id),
      CONSTRAINT fk_export_jobs_background_job FOREIGN KEY (workspace_id, background_job_id)
        REFERENCES edu.background_jobs(workspace_id, id),
      CONSTRAINT fk_export_jobs_content_revision FOREIGN KEY (workspace_id, content_revision_id)
        REFERENCES edu.content_revisions(workspace_id, id),
      CONSTRAINT fk_export_jobs_exam_version FOREIGN KEY (workspace_id, exam_version_id)
        REFERENCES edu.exam_versions(workspace_id, id),
      CONSTRAINT ck_export_jobs_one_source CHECK (
        num_nonnulls(content_revision_id, exam_version_id) = 1
      ),
      CONSTRAINT ck_export_jobs_failed CHECK ((status = 'failed') = (error_code IS NOT NULL)),
      CONSTRAINT ck_export_jobs_succeeded CHECK (
        (status = 'succeeded') = (object_key IS NOT NULL)
      ),
      CONSTRAINT ck_export_jobs_finished CHECK ((status = 'queued') = (finished_at IS NULL))
    );
    CREATE INDEX ix_export_jobs_listing ON edu.export_jobs(workspace_id, created_at DESC, id DESC);
    """)

    # Guards run as the invoker (RLS context of the caller) except the publication check, which
    # needs the key table and is a narrow SECURITY DEFINER function created further below.
    op.execute("""
    CREATE FUNCTION edu.generation_job_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
      BEGIN
        IF (NEW.id, NEW.workspace_id, NEW.background_job_id, NEW.requested_by_user_id,
            NEW.purpose, NEW.input, NEW.prompt_version, NEW.created_at)
           IS DISTINCT FROM
           (OLD.id, OLD.workspace_id, OLD.background_job_id, OLD.requested_by_user_id,
            OLD.purpose, OLD.input, OLD.prompt_version, OLD.created_at) THEN
          RAISE EXCEPTION 'generation job identity is immutable'
            USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.finished_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
          RAISE EXCEPTION 'finished generation job is immutable'
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END $$;
    CREATE TRIGGER generation_job_guard BEFORE UPDATE ON edu.generation_jobs
      FOR EACH ROW EXECUTE FUNCTION edu.generation_job_guard();

    CREATE FUNCTION edu.export_job_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
      BEGIN
        IF (NEW.id, NEW.workspace_id, NEW.background_job_id, NEW.content_revision_id,
            NEW.exam_version_id, NEW.format, NEW.audience, NEW.created_at)
           IS DISTINCT FROM
           (OLD.id, OLD.workspace_id, OLD.background_job_id, OLD.content_revision_id,
            OLD.exam_version_id, OLD.format, OLD.audience, OLD.created_at) THEN
          RAISE EXCEPTION 'export job identity is immutable' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status <> 'queued' AND NEW IS DISTINCT FROM OLD THEN
          RAISE EXCEPTION 'finished export job is immutable' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END $$;
    CREATE TRIGGER export_job_guard BEFORE UPDATE ON edu.export_jobs
      FOR EACH ROW EXECUTE FUNCTION edu.export_job_guard();

    CREATE FUNCTION edu.exam_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
      BEGIN
        IF (NEW.id, NEW.workspace_id, NEW.created_by_user_id, NEW.created_at)
           IS DISTINCT FROM (OLD.id, OLD.workspace_id, OLD.created_by_user_id, OLD.created_at)
        THEN
          RAISE EXCEPTION 'exam identity is immutable' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status = 'archived' AND NEW.status <> 'archived' THEN
          RAISE EXCEPTION 'archived exam cannot be reactivated'
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END $$;
    CREATE TRIGGER exam_guard BEFORE UPDATE ON edu.exams
      FOR EACH ROW EXECUTE FUNCTION edu.exam_guard();

    -- Items and keys may only be written while their version is a draft.
    CREATE FUNCTION edu.exam_snapshot_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
      DECLARE
        target uuid;
        version_status text;
      BEGIN
        IF TG_OP = 'INSERT' THEN
          target := NEW.exam_version_id;
        ELSE
          target := OLD.exam_version_id;
        END IF;
        SELECT v.status INTO version_status FROM edu.exam_versions v WHERE v.id = target;
        IF version_status IS DISTINCT FROM 'draft' THEN
          RAISE EXCEPTION 'exam version snapshot is immutable' USING ERRCODE = 'check_violation';
        END IF;
        IF TG_OP = 'UPDATE' THEN
          RAISE EXCEPTION 'exam snapshot rows are append-only' USING ERRCODE = 'check_violation';
        END IF;
        IF TG_OP = 'DELETE' THEN
          RETURN OLD;
        END IF;
        RETURN NEW;
      END $$;
    CREATE TRIGGER exam_items_snapshot_guard BEFORE INSERT OR UPDATE OR DELETE
      ON edu.exam_items FOR EACH ROW EXECUTE FUNCTION edu.exam_snapshot_guard();
    CREATE TRIGGER exam_answer_keys_snapshot_guard BEFORE INSERT OR UPDATE OR DELETE
      ON edu.exam_answer_keys FOR EACH ROW EXECUTE FUNCTION edu.exam_snapshot_guard();

    -- The key must name one of the item's choices (runtime can SELECT exam_items).
    CREATE FUNCTION edu.exam_answer_key_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
      BEGIN
        IF NOT EXISTS (
          SELECT 1 FROM edu.exam_items i, jsonb_array_elements(i.choices) AS c(value)
          WHERE i.id = NEW.exam_item_id AND i.workspace_id = NEW.workspace_id
            AND i.exam_version_id = NEW.exam_version_id AND c.value->>'key' = NEW.correct_key
        ) THEN
          RAISE EXCEPTION 'correct key must match a choice of the exam item'
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END $$;
    CREATE TRIGGER exam_answer_key_guard BEFORE INSERT ON edu.exam_answer_keys
      FOR EACH ROW EXECUTE FUNCTION edu.exam_answer_key_guard();

    REVOKE ALL ON FUNCTION edu.generation_job_guard(), edu.export_job_guard(), edu.exam_guard(),
      edu.exam_snapshot_guard(), edu.exam_answer_key_guard() FROM PUBLIC;
    """)

    for table in TENANT_TABLES:
        op.execute(f"""
        ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_tenant ON edu.{table} FOR ALL
          USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        """)

    # Narrow privileged readers owned by the NOLOGIN owner role (0004-0009 pattern). The tenant
    # policies still apply inside them; each function re-checks the workspace context itself.
    op.execute("""
    GRANT CREATE ON SCHEMA edu TO eduvia_identity_owner;
    GRANT SELECT ON edu.exam_answer_keys, edu.exam_items, edu.exam_versions
      TO eduvia_identity_owner;
    CREATE POLICY exam_answer_keys_key_function ON edu.exam_answer_keys FOR SELECT
      TO eduvia_identity_owner USING (true);

    -- Teacher-only key lookup; students and non-members get NULL.
    CREATE FUNCTION edu.exam_item_key(p_item_id uuid) RETURNS char
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
        SELECT k.correct_key FROM edu.exam_answer_keys k
        JOIN edu.workspace_members m ON m.workspace_id = k.workspace_id
        JOIN edu.users u ON u.id = m.user_id
        WHERE k.exam_item_id = p_item_id
          AND k.workspace_id::text = current_setting('edu.current_workspace_id', true)
          AND edu.can_read_workspace(k.workspace_id)
          AND m.user_id = edu.actor_id() AND m.status = 'active' AND u.is_active
          AND m.role IN ('owner','admin','teacher')
      $$;
    ALTER FUNCTION edu.exam_item_key(uuid) OWNER TO eduvia_identity_owner;

    -- Same checks; explanations are teacher material (teacher export / teacher DTO only).
    CREATE FUNCTION edu.exam_item_explanation(p_item_id uuid) RETURNS text
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
        SELECT k.explanation FROM edu.exam_answer_keys k
        JOIN edu.workspace_members m ON m.workspace_id = k.workspace_id
        JOIN edu.users u ON u.id = m.user_id
        WHERE k.exam_item_id = p_item_id
          AND k.workspace_id::text = current_setting('edu.current_workspace_id', true)
          AND edu.can_read_workspace(k.workspace_id)
          AND m.user_id = edu.actor_id() AND m.status = 'active' AND u.is_active
          AND m.role IN ('owner','admin','teacher')
      $$;
    ALTER FUNCTION edu.exam_item_explanation(uuid) OWNER TO eduvia_identity_owner;

    -- Scoring read: workspace context + membership + PUBLISHED version. No role check: the
    -- scoring worker runs as the job's actor. Errors: P0002 not visible, 42501 not published.
    CREATE FUNCTION edu.exam_keys_for_scoring(p_exam_version_id uuid)
      RETURNS TABLE(exam_item_id uuid, correct_key char, points numeric)
      LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
      DECLARE
        ws uuid;
        published timestamptz;
      BEGIN
        SELECT v.workspace_id, v.published_at INTO ws, published
          FROM edu.exam_versions v WHERE v.id = p_exam_version_id;
        IF ws IS NULL
           OR ws::text IS DISTINCT FROM current_setting('edu.current_workspace_id', true)
           OR NOT edu.can_read_workspace(ws) THEN
          RAISE EXCEPTION 'Exam version not found' USING ERRCODE = 'P0002';
        END IF;
        IF published IS NULL THEN
          RAISE EXCEPTION 'Exam version is not published' USING ERRCODE = '42501';
        END IF;
        RETURN QUERY
          SELECT k.exam_item_id, k.correct_key, i.points
          FROM edu.exam_answer_keys k
          JOIN edu.exam_items i
            ON i.workspace_id = k.workspace_id AND i.exam_version_id = k.exam_version_id
           AND i.id = k.exam_item_id
          WHERE k.workspace_id = ws AND k.exam_version_id = p_exam_version_id
          ORDER BY i.position;
      END $$;
    ALTER FUNCTION edu.exam_keys_for_scoring(uuid) OWNER TO eduvia_identity_owner;

    -- Publication rules; returns NULL when publishable, else a stable error code.
    CREATE FUNCTION edu.exam_version_publish_error(p_exam_version_id uuid) RETURNS text
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
        SELECT CASE
          WHEN v.id IS NULL
               OR v.workspace_id::text IS DISTINCT FROM
                  current_setting('edu.current_workspace_id', true)
               OR NOT edu.can_read_workspace(v.workspace_id) THEN 'exam_version_not_found'
          WHEN stats.items = 0 THEN 'exam_empty'
          WHEN stats.bad_choices > 0 THEN 'invalid_choices'
          WHEN stats.bad_points > 0 THEN 'invalid_points'
          WHEN stats.keys <> stats.items THEN 'missing_key'
          WHEN stats.bad_keys > 0 THEN 'invalid_key'
          WHEN stats.total IS DISTINCT FROM v.total_points THEN 'points_mismatch'
        END
        FROM (SELECT p_exam_version_id AS id) target
        LEFT JOIN edu.exam_versions v ON v.id = target.id
        CROSS JOIN LATERAL (
          SELECT count(i.id) AS items,
                 count(*) FILTER (
                   WHERE jsonb_array_length(i.choices) NOT BETWEEN 3 AND 5) AS bad_choices,
                 count(*) FILTER (WHERE i.points <= 0) AS bad_points,
                 count(k.exam_item_id) AS keys,
                 count(*) FILTER (
                   WHERE k.exam_item_id IS NOT NULL AND NOT EXISTS (
                     SELECT 1 FROM jsonb_array_elements(i.choices) AS c(value)
                     WHERE c.value->>'key' = k.correct_key)) AS bad_keys,
                 coalesce(sum(i.points), 0)::numeric(10,2) AS total
          FROM edu.exam_items i
          LEFT JOIN edu.exam_answer_keys k
            ON k.workspace_id = i.workspace_id AND k.exam_item_id = i.id
          WHERE i.workspace_id = v.workspace_id AND i.exam_version_id = v.id
        ) stats
      $$;
    ALTER FUNCTION edu.exam_version_publish_error(uuid) OWNER TO eduvia_identity_owner;

    REVOKE ALL ON FUNCTION edu.exam_item_key(uuid), edu.exam_item_explanation(uuid),
      edu.exam_keys_for_scoring(uuid), edu.exam_version_publish_error(uuid) FROM PUBLIC;
    REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner;
    """)

    # Version guard (invoker): identity immutable, published payload frozen, transitions
    # draft -> published|archived and published -> archived, validated publication.
    op.execute("""
    CREATE FUNCTION edu.exam_version_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
      DECLARE
        problem text;
      BEGIN
        IF TG_OP = 'INSERT' THEN
          IF NEW.status <> 'draft' OR NEW.published_at IS NOT NULL
             OR NEW.published_by_user_id IS NOT NULL THEN
            RAISE EXCEPTION 'exam versions start as draft' USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END IF;
        IF TG_OP = 'DELETE' THEN
          IF OLD.published_at IS NOT NULL OR OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'published exam version is immutable'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN OLD;
        END IF;
        IF (NEW.id, NEW.workspace_id, NEW.exam_id, NEW.version_no, NEW.blueprint_version_id,
            NEW.created_at)
           IS DISTINCT FROM
           (OLD.id, OLD.workspace_id, OLD.exam_id, OLD.version_no, OLD.blueprint_version_id,
            OLD.created_at) THEN
          RAISE EXCEPTION 'exam version identity is immutable'
            USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.published_at IS NOT NULL
           AND (NEW.total_points, NEW.content_hash, NEW.published_at, NEW.published_by_user_id)
               IS DISTINCT FROM
               (OLD.total_points, OLD.content_hash, OLD.published_at, OLD.published_by_user_id)
        THEN
          RAISE EXCEPTION 'published exam version is immutable'
            USING ERRCODE = 'check_violation';
        END IF;
        IF NOT (NEW.status = OLD.status
                OR (OLD.status = 'draft' AND NEW.status IN ('published','archived'))
                OR (OLD.status = 'published' AND NEW.status = 'archived')) THEN
          RAISE EXCEPTION 'invalid exam version transition' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status = 'archived' AND NEW IS DISTINCT FROM OLD THEN
          RAISE EXCEPTION 'archived exam version is immutable'
            USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status = 'draft' AND NEW.status = 'published' THEN
          -- The check reads the stored row, so the total cannot change in the same statement.
          IF NEW.total_points IS DISTINCT FROM OLD.total_points THEN
            RAISE EXCEPTION 'exam version cannot be published: points_changed'
              USING ERRCODE = 'check_violation';
          END IF;
          problem := edu.exam_version_publish_error(NEW.id);
          IF problem IS NOT NULL THEN
            RAISE EXCEPTION 'exam version cannot be published: %', problem
              USING ERRCODE = 'check_violation';
          END IF;
        END IF;
        RETURN NEW;
      END $$;
    CREATE TRIGGER exam_version_guard BEFORE INSERT OR UPDATE OR DELETE ON edu.exam_versions
      FOR EACH ROW EXECUTE FUNCTION edu.exam_version_guard();
    REVOKE ALL ON FUNCTION edu.exam_version_guard() FROM PUBLIC;
    """)

    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduvia_runtime') THEN
        -- Default privileges grant more; replace them with the exact lean set.
        REVOKE ALL ON edu.generation_jobs, edu.generation_sources, edu.exams,
          edu.exam_versions, edu.exam_items, edu.exam_answer_keys, edu.export_jobs
          FROM eduvia_runtime;
        GRANT SELECT, INSERT, UPDATE ON edu.generation_jobs, edu.exams, edu.exam_versions,
          edu.export_jobs TO eduvia_runtime;
        -- Provenance and snapshot rows are append-only.
        GRANT SELECT, INSERT ON edu.generation_sources, edu.exam_items TO eduvia_runtime;
        -- Keys: INSERT only, deliberately NO SELECT (same rationale as question_keys).
        GRANT INSERT ON edu.exam_answer_keys TO eduvia_runtime;
        GRANT EXECUTE ON FUNCTION edu.exam_item_key(uuid), edu.exam_item_explanation(uuid),
          edu.exam_keys_for_scoring(uuid), edu.exam_version_publish_error(uuid)
          TO eduvia_runtime;
      END IF;
    END $$;
    """)


def downgrade():
    raise RuntimeError("Generation migration is forward-only; restore a reviewed backup instead")
