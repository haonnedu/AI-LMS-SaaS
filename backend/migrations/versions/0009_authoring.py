"""M4 manual authoring foundation: content revisions + review, question bank with separated
keys, and versioned exam blueprints (AUTHR-01/02, QB-01/02, BP-01/02).

* Every table is tenant-owned: ``workspace_id NOT NULL``, ``UNIQUE (workspace_id, id)``,
  composite (workspace_id, ...) foreign keys and the 0006/0007 FORCE RLS predicate.
* ``content_revisions``: only ``draft`` payloads are mutable (autosave); once submitted the
  body is frozen. Transitions draft -> in_review -> approved -> published, any -> archived;
  ``archived`` is terminal and reviewer/publication stamps can never be rewritten.
* ``question_revisions`` are append-only (no UPDATE grant): every edit is a new revision.
* ``question_keys`` is a separate table so no student-facing query can join it by accident.
  The runtime role has INSERT only (keys are immutable per revision; changing a key creates a
  new question revision) and **no SELECT grant at all**: an UPDATE ... WHERE would itself need
  SELECT on the filtered column, so UPDATE is not granted either. Staff read keys only through
  the SECURITY DEFINER ``edu.question_key(revision)``, which re-checks the transaction's
  workspace context, ``edu.can_read_workspace`` and an owner/admin/teacher membership role.
* ``questions.item_type`` is a CHECK-constrained text column holding only ``single_choice``
  for the pilot. True/false-multi or short-answer later replace that CHECK (and relax the
  revision ``choices``/key constraints or add nullable payload columns) without rewriting
  existing rows.
* ``blueprint_versions``: body/hash are immutable from creation (each edit is a new version);
  the validation report may change until publication; published versions are frozen.
* Blueprints are ``teacher_defined`` only: tenant staff cannot self-label a blueprint official.
"""

from alembic import op

revision = "0009_authoring"
down_revision = "0008_retrieval"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "content_items",
    "content_revisions",
    "review_requests",
    "questions",
    "question_revisions",
    "question_keys",
    "question_objectives",
    "blueprints",
    "blueprint_versions",
)

TENANT_PREDICATE = (
    "workspace_id::text = current_setting('edu.current_workspace_id', true) "
    "AND edu.can_read_workspace(workspace_id)"
)

MAX_BODY_BYTES = 204800


def upgrade():
    op.execute(f"""
    CREATE TABLE edu.content_items (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      kind text NOT NULL CHECK (kind IN ('lesson_plan','study_guide')),
      title text NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
      created_by_user_id uuid NOT NULL REFERENCES edu.users(id),
      status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','in_review','published','archived')),
      current_revision_id uuid,
      latest_revision_no integer NOT NULL DEFAULT 0 CHECK (latest_revision_no >= 0),
      curriculum_unit_id uuid REFERENCES edu.curriculum_units(id),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      deleted_at timestamptz,
      CONSTRAINT uq_content_items_workspace_id UNIQUE (workspace_id, id),
      CONSTRAINT ck_content_items_published CHECK (
        status <> 'published' OR current_revision_id IS NOT NULL
      )
    );
    CREATE INDEX ix_content_items_listing
      ON edu.content_items(workspace_id, created_at DESC, id DESC);

    CREATE TABLE edu.content_revisions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      content_item_id uuid NOT NULL,
      revision_no integer NOT NULL CHECK (revision_no > 0),
      body jsonb NOT NULL CHECK (
        jsonb_typeof(body) = 'object' AND octet_length(body::text) <= {MAX_BODY_BYTES}
      ),
      audience text NOT NULL DEFAULT 'teacher' CHECK (audience IN ('teacher','student')),
      status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','in_review','approved','published','archived')),
      based_on_revision_id uuid,
      generation_job_id uuid,
      created_by_user_id uuid NOT NULL REFERENCES edu.users(id),
      reviewed_by_user_id uuid REFERENCES edu.users(id),
      reviewed_at timestamptz,
      published_at timestamptz,
      body_sha256 bytea NOT NULL CHECK (octet_length(body_sha256) = 32),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CONSTRAINT uq_content_revisions_number UNIQUE (content_item_id, revision_no),
      CONSTRAINT uq_content_revisions_workspace_id UNIQUE (workspace_id, id),
      CONSTRAINT uq_content_revisions_owner UNIQUE (workspace_id, content_item_id, id),
      CONSTRAINT fk_content_revisions_item FOREIGN KEY (workspace_id, content_item_id)
        REFERENCES edu.content_items(workspace_id, id),
      CONSTRAINT fk_content_revisions_based_on FOREIGN KEY (workspace_id, based_on_revision_id)
        REFERENCES edu.content_revisions(workspace_id, id),
      CONSTRAINT fk_content_revisions_generation_job FOREIGN KEY (workspace_id, generation_job_id)
        REFERENCES edu.background_jobs(workspace_id, id),
      CONSTRAINT ck_content_revisions_reviewed CHECK (
        status NOT IN ('approved','published')
        OR (reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)
      ),
      CONSTRAINT ck_content_revisions_published CHECK (
        status <> 'published' OR published_at IS NOT NULL
      )
    );
    CREATE INDEX ix_content_revisions_history
      ON edu.content_revisions(workspace_id, content_item_id, revision_no DESC);

    ALTER TABLE edu.content_items ADD CONSTRAINT fk_content_items_current_revision
      FOREIGN KEY (workspace_id, id, current_revision_id)
      REFERENCES edu.content_revisions(workspace_id, content_item_id, id)
      DEFERRABLE INITIALLY DEFERRED;

    -- At most one open review request per revision (partial unique index below).
    CREATE TABLE edu.review_requests (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      content_revision_id uuid NOT NULL,
      requested_by_user_id uuid NOT NULL REFERENCES edu.users(id),
      assigned_to_user_id uuid REFERENCES edu.users(id),
      status text NOT NULL DEFAULT 'open'
        CHECK (status IN ('open','changes_requested','approved','rejected')),
      comment text CHECK (comment IS NULL OR length(comment) <= 4000),
      decided_by_user_id uuid REFERENCES edu.users(id),
      decided_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CONSTRAINT uq_review_requests_workspace_id UNIQUE (workspace_id, id),
      CONSTRAINT fk_review_requests_revision FOREIGN KEY (workspace_id, content_revision_id)
        REFERENCES edu.content_revisions(workspace_id, id),
      CONSTRAINT ck_review_requests_decided CHECK (
        (status = 'open') = (decided_by_user_id IS NULL AND decided_at IS NULL)
      )
    );
    CREATE UNIQUE INDEX uq_review_requests_open
      ON edu.review_requests(content_revision_id) WHERE status = 'open';

    CREATE TABLE edu.questions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      item_type text NOT NULL DEFAULT 'single_choice' CHECK (item_type IN ('single_choice')),
      stem text NOT NULL CHECK (length(stem) BETWEEN 1 AND 10000),
      stem_sha256 bytea NOT NULL CHECK (octet_length(stem_sha256) = 32),
      status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','retired')),
      difficulty smallint CHECK (difficulty IS NULL OR difficulty BETWEEN 1 AND 5),
      cognitive_level text NOT NULL
        CHECK (cognitive_level IN ('remember','understand','apply','analyze')),
      curriculum_unit_id uuid REFERENCES edu.curriculum_units(id),
      source_citations jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
        jsonb_typeof(source_citations) = 'array' AND jsonb_array_length(source_citations) <= 50
      ),
      created_by_user_id uuid NOT NULL REFERENCES edu.users(id),
      current_revision_id uuid,
      latest_revision_no integer NOT NULL DEFAULT 0 CHECK (latest_revision_no >= 0),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CONSTRAINT uq_questions_workspace_id UNIQUE (workspace_id, id)
    );
    CREATE INDEX ix_questions_listing ON edu.questions(workspace_id, created_at DESC, id DESC);
    CREATE INDEX ix_questions_filters
      ON edu.questions(workspace_id, curriculum_unit_id, cognitive_level, difficulty);
    CREATE INDEX ix_questions_stem_hash ON edu.questions(workspace_id, stem_sha256);

    CREATE TABLE edu.question_revisions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      question_id uuid NOT NULL,
      revision_no integer NOT NULL CHECK (revision_no > 0),
      stem text NOT NULL CHECK (length(stem) BETWEEN 1 AND 10000),
      choices jsonb NOT NULL CHECK (
        jsonb_typeof(choices) = 'array' AND jsonb_array_length(choices) BETWEEN 3 AND 5
      ),
      explanation text CHECK (explanation IS NULL OR length(explanation) <= 10000),
      created_by_user_id uuid NOT NULL REFERENCES edu.users(id),
      body_sha256 bytea NOT NULL CHECK (octet_length(body_sha256) = 32),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CONSTRAINT uq_question_revisions_number UNIQUE (question_id, revision_no),
      CONSTRAINT uq_question_revisions_workspace_id UNIQUE (workspace_id, id),
      CONSTRAINT uq_question_revisions_owner UNIQUE (workspace_id, question_id, id),
      CONSTRAINT fk_question_revisions_question FOREIGN KEY (workspace_id, question_id)
        REFERENCES edu.questions(workspace_id, id)
    );

    ALTER TABLE edu.questions ADD CONSTRAINT fk_questions_current_revision
      FOREIGN KEY (workspace_id, id, current_revision_id)
      REFERENCES edu.question_revisions(workspace_id, question_id, id)
      DEFERRABLE INITIALLY DEFERRED;

    CREATE TABLE edu.question_keys (
      question_revision_id uuid PRIMARY KEY,
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      correct_key char(1) NOT NULL CHECK (correct_key IN ('A','B','C','D','E')),
      rationale text CHECK (rationale IS NULL OR length(rationale) <= 10000),
      set_by_user_id uuid NOT NULL REFERENCES edu.users(id),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CONSTRAINT fk_question_keys_revision FOREIGN KEY (workspace_id, question_revision_id)
        REFERENCES edu.question_revisions(workspace_id, id)
    );

    CREATE TABLE edu.question_objectives (
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      question_id uuid NOT NULL,
      curriculum_unit_id uuid NOT NULL REFERENCES edu.curriculum_units(id),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY (question_id, curriculum_unit_id),
      CONSTRAINT fk_question_objectives_question FOREIGN KEY (workspace_id, question_id)
        REFERENCES edu.questions(workspace_id, id)
    );
    CREATE INDEX ix_question_objectives_unit
      ON edu.question_objectives(workspace_id, curriculum_unit_id);

    CREATE TABLE edu.blueprints (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      title text NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
      subject_id uuid NOT NULL REFERENCES edu.curriculum_subjects(id),
      grade smallint NOT NULL CHECK (grade BETWEEN 1 AND 12),
      program_year text NOT NULL DEFAULT '2018' CHECK (program_year ~ '^[0-9]{{4}}$'),
      exam_kind text NOT NULL CHECK (exam_kind IN ('periodic','mock')),
      duration_minutes integer NOT NULL CHECK (duration_minutes BETWEEN 1 AND 600),
      total_points numeric(6,2) NOT NULL CHECK (total_points > 0),
      status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','validated','published','archived')),
      current_version_id uuid,
      latest_version_no integer NOT NULL DEFAULT 0 CHECK (latest_version_no >= 0),
      effective_year smallint NOT NULL CHECK (effective_year BETWEEN 2000 AND 2100),
      origin_kind text NOT NULL DEFAULT 'teacher_defined'
        CHECK (origin_kind IN ('teacher_defined')),
      provenance text NOT NULL CHECK (length(provenance) BETWEEN 1 AND 2000),
      created_by_user_id uuid NOT NULL REFERENCES edu.users(id),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CONSTRAINT uq_blueprints_workspace_id UNIQUE (workspace_id, id)
    );
    CREATE INDEX ix_blueprints_listing ON edu.blueprints(workspace_id, created_at DESC, id DESC);

    CREATE TABLE edu.blueprint_versions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      blueprint_id uuid NOT NULL,
      version_no integer NOT NULL CHECK (version_no > 0),
      body jsonb NOT NULL CHECK (
        jsonb_typeof(body) = 'object' AND octet_length(body::text) <= {MAX_BODY_BYTES}
      ),
      status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','validated','published','archived')),
      validation_report jsonb NOT NULL DEFAULT '{{}}'::jsonb
        CHECK (jsonb_typeof(validation_report) = 'object'),
      body_sha256 bytea NOT NULL CHECK (octet_length(body_sha256) = 32),
      created_by_user_id uuid NOT NULL REFERENCES edu.users(id),
      published_by_user_id uuid REFERENCES edu.users(id),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      validated_at timestamptz,
      published_at timestamptz,
      CONSTRAINT uq_blueprint_versions_number UNIQUE (blueprint_id, version_no),
      CONSTRAINT uq_blueprint_versions_workspace_id UNIQUE (workspace_id, id),
      CONSTRAINT uq_blueprint_versions_owner UNIQUE (workspace_id, blueprint_id, id),
      CONSTRAINT fk_blueprint_versions_blueprint FOREIGN KEY (workspace_id, blueprint_id)
        REFERENCES edu.blueprints(workspace_id, id),
      CONSTRAINT ck_blueprint_versions_published CHECK (
        status <> 'published' OR (published_at IS NOT NULL AND published_by_user_id IS NOT NULL)
      )
    );

    ALTER TABLE edu.blueprints ADD CONSTRAINT fk_blueprints_current_version
      FOREIGN KEY (workspace_id, id, current_version_id)
      REFERENCES edu.blueprint_versions(workspace_id, blueprint_id, id)
      DEFERRABLE INITIALLY DEFERRED;
    """)

    # Immutability/transition guards (invoker triggers; they run under the caller's RLS context).
    op.execute("""
    CREATE FUNCTION edu.content_revision_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
      BEGIN
        IF TG_OP = 'INSERT' THEN
          IF NEW.status <> 'draft' OR NEW.reviewed_by_user_id IS NOT NULL
             OR NEW.reviewed_at IS NOT NULL OR NEW.published_at IS NOT NULL THEN
            RAISE EXCEPTION 'content revisions start as draft'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END IF;
        IF (NEW.id, NEW.workspace_id, NEW.content_item_id, NEW.revision_no,
            NEW.based_on_revision_id, NEW.generation_job_id, NEW.created_by_user_id,
            NEW.created_at)
           IS DISTINCT FROM
           (OLD.id, OLD.workspace_id, OLD.content_item_id, OLD.revision_no,
            OLD.based_on_revision_id, OLD.generation_job_id, OLD.created_by_user_id,
            OLD.created_at) THEN
          RAISE EXCEPTION 'content revision identity is immutable'
            USING ERRCODE = 'check_violation';
        END IF;
        -- Only a draft payload is editable (autosave); submitted/approved/published are frozen.
        IF OLD.status <> 'draft' AND (NEW.body, NEW.body_sha256, NEW.audience)
           IS DISTINCT FROM (OLD.body, OLD.body_sha256, OLD.audience) THEN
          RAISE EXCEPTION 'submitted content revision is immutable'
            USING ERRCODE = 'check_violation';
        END IF;
        IF (OLD.reviewed_by_user_id IS NOT NULL OR OLD.reviewed_at IS NOT NULL)
           AND (NEW.reviewed_by_user_id, NEW.reviewed_at)
               IS DISTINCT FROM (OLD.reviewed_by_user_id, OLD.reviewed_at) THEN
          RAISE EXCEPTION 'review stamp is immutable' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.published_at IS NOT NULL AND NEW.published_at IS DISTINCT FROM OLD.published_at
        THEN
          RAISE EXCEPTION 'publication stamp is immutable' USING ERRCODE = 'check_violation';
        END IF;
        IF NOT (NEW.status = OLD.status
                OR (OLD.status = 'draft' AND NEW.status = 'in_review')
                OR (OLD.status = 'in_review' AND NEW.status = 'approved')
                OR (OLD.status = 'approved' AND NEW.status = 'published')
                OR (OLD.status <> 'archived' AND NEW.status = 'archived')) THEN
          RAISE EXCEPTION 'invalid content revision transition'
            USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status = 'archived' AND NEW IS DISTINCT FROM OLD THEN
          RAISE EXCEPTION 'archived content revision is immutable'
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END $$;
    CREATE TRIGGER content_revision_guard BEFORE INSERT OR UPDATE ON edu.content_revisions
      FOR EACH ROW EXECUTE FUNCTION edu.content_revision_guard();

    CREATE FUNCTION edu.question_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
      BEGIN
        IF (NEW.id, NEW.workspace_id, NEW.item_type, NEW.created_by_user_id, NEW.created_at)
           IS DISTINCT FROM
           (OLD.id, OLD.workspace_id, OLD.item_type, OLD.created_by_user_id, OLD.created_at) THEN
          RAISE EXCEPTION 'question identity is immutable' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status = 'retired' AND NEW.status <> 'retired' THEN
          RAISE EXCEPTION 'retired question cannot be reactivated'
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END $$;
    CREATE TRIGGER question_guard BEFORE UPDATE ON edu.questions
      FOR EACH ROW EXECUTE FUNCTION edu.question_guard();

    -- The key must name one of the revision's choices (checked under the caller's RLS).
    CREATE FUNCTION edu.question_key_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
      BEGIN
        IF NOT EXISTS (
          SELECT 1 FROM edu.question_revisions r, jsonb_array_elements(r.choices) AS c(value)
          WHERE r.id = NEW.question_revision_id AND r.workspace_id = NEW.workspace_id
            AND c.value->>'key' = NEW.correct_key
        ) THEN
          RAISE EXCEPTION 'correct key must match a choice of the revision'
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END $$;
    CREATE TRIGGER question_key_guard BEFORE INSERT ON edu.question_keys
      FOR EACH ROW EXECUTE FUNCTION edu.question_key_guard();

    CREATE FUNCTION edu.blueprint_version_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
      BEGIN
        IF (NEW.id, NEW.workspace_id, NEW.blueprint_id, NEW.version_no, NEW.body,
            NEW.body_sha256, NEW.created_by_user_id, NEW.created_at)
           IS DISTINCT FROM
           (OLD.id, OLD.workspace_id, OLD.blueprint_id, OLD.version_no, OLD.body,
            OLD.body_sha256, OLD.created_by_user_id, OLD.created_at) THEN
          RAISE EXCEPTION 'blueprint version body is immutable'
            USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.published_at IS NOT NULL
           AND (NEW.validation_report, NEW.validated_at, NEW.published_at,
                NEW.published_by_user_id)
               IS DISTINCT FROM
               (OLD.validation_report, OLD.validated_at, OLD.published_at,
                OLD.published_by_user_id) THEN
          RAISE EXCEPTION 'published blueprint version is immutable'
            USING ERRCODE = 'check_violation';
        END IF;
        IF NOT (NEW.status = OLD.status
                OR (OLD.status = 'draft' AND NEW.status = 'validated')
                OR (OLD.status = 'validated' AND NEW.status IN ('draft','published'))
                OR (OLD.status <> 'archived' AND NEW.status = 'archived')) THEN
          RAISE EXCEPTION 'invalid blueprint version transition'
            USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status = 'archived' AND NEW IS DISTINCT FROM OLD THEN
          RAISE EXCEPTION 'archived blueprint version is immutable'
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END $$;
    CREATE TRIGGER blueprint_version_guard BEFORE UPDATE ON edu.blueprint_versions
      FOR EACH ROW EXECUTE FUNCTION edu.blueprint_version_guard();

    REVOKE ALL ON FUNCTION edu.content_revision_guard(), edu.question_guard(),
      edu.question_key_guard(), edu.blueprint_version_guard() FROM PUBLIC;
    """)

    for table in TENANT_TABLES:
        op.execute(f"""
        ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_tenant ON edu.{table} FOR ALL
          USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        """)

    # Narrow privileged readers (NOLOGIN owner role as in 0004-0006).
    op.execute("""
    GRANT CREATE ON SCHEMA edu TO eduvia_identity_owner;
    GRANT SELECT ON edu.question_keys TO eduvia_identity_owner;
    CREATE POLICY question_keys_key_function ON edu.question_keys FOR SELECT
      TO eduvia_identity_owner USING (true);

    -- Teacher-only key lookup. Students and non-members get NULL; the runtime role itself has
    -- no SELECT on question_keys, so a student-facing query can never join it.
    CREATE FUNCTION edu.question_key(p_revision_id uuid) RETURNS char
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
        SELECT k.correct_key FROM edu.question_keys k
        JOIN edu.workspace_members m ON m.workspace_id = k.workspace_id
        JOIN edu.users u ON u.id = m.user_id
        WHERE k.question_revision_id = p_revision_id
          AND k.workspace_id::text = current_setting('edu.current_workspace_id', true)
          AND edu.can_read_workspace(k.workspace_id)
          AND m.user_id = edu.actor_id() AND m.status = 'active' AND u.is_active
          AND m.role IN ('owner','admin','teacher')
      $$;
    ALTER FUNCTION edu.question_key(uuid) OWNER TO eduvia_identity_owner;

    -- Number of active staff in the CURRENT workspace (self-approval is allowed only when the
    -- author is the sole staff member). Returns NULL outside a verified workspace context.
    CREATE FUNCTION edu.workspace_staff_count(p_workspace uuid) RETURNS integer
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
        SELECT CASE
          WHEN p_workspace::text = current_setting('edu.current_workspace_id', true)
               AND edu.can_read_workspace(p_workspace)
          THEN (SELECT count(*)::integer
                FROM edu.workspace_members m JOIN edu.users u ON u.id = m.user_id
                WHERE m.workspace_id = p_workspace AND m.status = 'active' AND u.is_active
                  AND m.role IN ('owner','admin','teacher'))
        END
      $$;
    ALTER FUNCTION edu.workspace_staff_count(uuid) OWNER TO eduvia_identity_owner;
    REVOKE ALL ON FUNCTION edu.question_key(uuid), edu.workspace_staff_count(uuid) FROM PUBLIC;
    REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner;
    """)

    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduvia_runtime') THEN
        -- Default privileges grant more; replace them with the exact lean set.
        REVOKE ALL ON edu.content_items, edu.content_revisions, edu.review_requests,
          edu.questions, edu.question_revisions, edu.question_keys, edu.question_objectives,
          edu.blueprints, edu.blueprint_versions FROM eduvia_runtime;
        GRANT SELECT, INSERT, UPDATE ON edu.content_items, edu.content_revisions,
          edu.review_requests, edu.questions, edu.blueprints, edu.blueprint_versions
          TO eduvia_runtime;
        -- Question revisions are append-only: every edit is a new revision.
        GRANT SELECT, INSERT ON edu.question_revisions TO eduvia_runtime;
        -- Keys: INSERT only, deliberately NO SELECT (and therefore no UPDATE, which would need
        -- SELECT on its WHERE column). Staff read keys via edu.question_key() only.
        GRANT INSERT ON edu.question_keys TO eduvia_runtime;
        -- Objective mappings are a replaceable association set (replace = delete + insert).
        GRANT SELECT, INSERT, DELETE ON edu.question_objectives TO eduvia_runtime;
        GRANT EXECUTE ON FUNCTION edu.question_key(uuid), edu.workspace_staff_count(uuid)
          TO eduvia_runtime;
      END IF;
    END $$;
    """)


def downgrade():
    raise RuntimeError("Authoring migration is forward-only; restore a reviewed backup instead")
