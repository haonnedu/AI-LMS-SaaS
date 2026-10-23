"""M3 knowledge (provider-independent half): curriculum metadata, private-only rights scope,
immutable document versions with an activation invariant, and versioned chunks.

* ``curriculum_subjects`` / ``curriculum_units`` are platform-wide metadata (no tenant text):
  RLS is enabled and FORCEd with a ``USING (true)`` SELECT policy; the runtime role only reads.
* ``document_versions`` / ``document_chunks`` / ``document_curriculum_tags`` are tenant tables
  with the 0006 FORCE RLS predicate and composite (workspace_id, ...) foreign keys.
* At most one ``active`` version per document (partial unique index): a failed ingest can never
  replace the active version. Version identity and finished content are immutable (trigger);
  chunks are append-only and may only be added while their version is ``processing``.
* ``documents.rights_scope`` only allows ``'private'``: uploads are never promoted to a shared
  corpus (shared/licensed catalog is a separate, not-yet-approved design).
No vector column here: embeddings (KNOW-06) get their own migration once the model is chosen.
"""

import uuid

from alembic import op

revision = "0010_knowledge"
down_revision = "0009_jobs_storage"
branch_labels = None
depends_on = None

TENANT_TABLES = ("document_versions", "document_chunks", "document_curriculum_tags")
CATALOG_TABLES = ("curriculum_subjects", "curriculum_units")

TENANT_PREDICATE = (
    "workspace_id::text = current_setting('edu.current_workspace_id', true) "
    "AND edu.can_read_workspace(workspace_id)"
)

# Stable IDs so every environment (and future revision migrations) agree on the seed rows.
SEED_NAMESPACE = uuid.UUID("6b0f7c62-3f5e-4d0a-9a51-0c2f0c7e2a07")
SEED_PROVENANCE = "seed:pilot-draft"
SUBJECTS = (("toan", "Toán"), ("ngu-van", "Ngữ văn"), ("tieng-anh", "Tiếng Anh"))
# Draft chapter-level topics of the 2018 general-education Mathematics programme (grades 10-12)
# for the pilot. Pedagogy owners revise them via a later migration (bump ``version``).
TOAN_UNITS = (
    (10, "T10-01", "Mệnh đề và tập hợp"),
    (10, "T10-02", "Bất phương trình và hệ bất phương trình bậc nhất hai ẩn"),
    (10, "T10-03", "Hệ thức lượng trong tam giác"),
    (10, "T10-04", "Vectơ"),
    (10, "T10-05", "Hàm số, đồ thị và ứng dụng"),
    (11, "T11-01", "Hàm số lượng giác và phương trình lượng giác"),
    (11, "T11-02", "Dãy số. Cấp số cộng và cấp số nhân"),
    (11, "T11-03", "Giới hạn. Hàm số liên tục"),
    (11, "T11-04", "Hàm số mũ và hàm số lôgarit"),
    (11, "T11-05", "Đạo hàm"),
    (12, "T12-01", "Ứng dụng đạo hàm để khảo sát và vẽ đồ thị hàm số"),
    (12, "T12-02", "Nguyên hàm và tích phân"),
    (12, "T12-03", "Vectơ và hệ trục tọa độ trong không gian"),
    (12, "T12-04", "Phương pháp tọa độ trong không gian"),
    (12, "T12-05", "Xác suất có điều kiện"),
)


def subject_id(code: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"subject:{code}")


def unit_id(subject: str, grade: int, program_year: str, code: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"unit:{subject}:{grade}:{program_year}:{code}")


def _literal(value: str) -> str:
    assert "'" not in value and "\\" not in value, value
    return f"'{value}'"


def seed_sql() -> str:
    subjects = ",\n      ".join(
        f"('{subject_id(code)}', {_literal(code)}, {_literal(name)})" for code, name in SUBJECTS
    )
    units = ",\n      ".join(
        f"('{unit_id('toan', grade, '2018', code)}', '{subject_id('toan')}', {grade}, '2018', "
        f"{_literal(code)}, {_literal(title)}, {position}, '{SEED_PROVENANCE}')"
        for position, (grade, code, title) in enumerate(TOAN_UNITS, start=1)
    )
    return f"""
    INSERT INTO edu.curriculum_subjects(id, code, name_vi) VALUES
      {subjects};
    INSERT INTO edu.curriculum_units(id, subject_id, grade, program_year, unit_code, title_vi,
      sort_order, source_provenance) VALUES
      {units};
    """


def upgrade():
    op.execute("""
    CREATE TABLE edu.curriculum_subjects (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      code text NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9-]{1,32}$'),
      name_vi text NOT NULL CHECK (length(name_vi) BETWEEN 1 AND 100),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );

    CREATE TABLE edu.curriculum_units (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      subject_id uuid NOT NULL REFERENCES edu.curriculum_subjects(id),
      grade smallint NOT NULL CHECK (grade BETWEEN 1 AND 12),
      program_year text NOT NULL DEFAULT '2018' CHECK (program_year ~ '^[0-9]{4}$'),
      unit_code text NOT NULL CHECK (length(unit_code) BETWEEN 1 AND 64),
      title_vi text NOT NULL CHECK (length(title_vi) BETWEEN 1 AND 300),
      parent_id uuid REFERENCES edu.curriculum_units(id),
      sort_order integer NOT NULL DEFAULT 0,
      source_provenance text NOT NULL CHECK (length(source_provenance) BETWEEN 1 AND 200),
      version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CONSTRAINT uq_curriculum_units_scope UNIQUE (subject_id, grade, program_year, unit_code),
      CONSTRAINT ck_curriculum_units_not_self_parent CHECK (parent_id IS DISTINCT FROM id)
    );
    CREATE INDEX ix_curriculum_units_listing
      ON edu.curriculum_units(subject_id, grade, sort_order);
    """)

    op.execute(seed_sql())

    op.execute("""
    -- KNOW-02: private-only rights scope; an unattested document can never get a version
    -- activated. active_version_id is checked by a deferred composite FK added below.
    ALTER TABLE edu.documents
      ADD COLUMN rights_scope text NOT NULL DEFAULT 'private',
      ADD COLUMN active_version_id uuid,
      ADD CONSTRAINT ck_documents_rights_scope CHECK (rights_scope IN ('private')),
      ADD CONSTRAINT ck_documents_active_requires_rights
        CHECK (active_version_id IS NULL OR rights_attested),
      ADD CONSTRAINT uq_documents_workspace_id UNIQUE (workspace_id, id);

    CREATE TABLE edu.document_versions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      document_id uuid NOT NULL,
      version_no integer NOT NULL CHECK (version_no > 0),
      status text NOT NULL DEFAULT 'processing'
        CHECK (status IN ('processing','active','failed','superseded')),
      parser text NOT NULL CHECK (length(parser) BETWEEN 1 AND 64),
      parser_version text NOT NULL CHECK (length(parser_version) BETWEEN 1 AND 64),
      chunker_version text NOT NULL CHECK (length(chunker_version) BETWEEN 1 AND 32),
      page_count integer CHECK (page_count IS NULL OR page_count >= 0),
      char_count integer NOT NULL DEFAULT 0 CHECK (char_count >= 0),
      chunk_count integer NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
      text_sha256 bytea CHECK (text_sha256 IS NULL OR octet_length(text_sha256) = 32),
      error_code text CHECK (error_code IS NULL OR length(error_code) BETWEEN 1 AND 64),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      activated_at timestamptz,
      CONSTRAINT uq_document_versions_number UNIQUE (document_id, version_no),
      CONSTRAINT uq_document_versions_workspace_id UNIQUE (workspace_id, id),
      CONSTRAINT uq_document_versions_owner UNIQUE (workspace_id, document_id, id),
      CONSTRAINT fk_document_versions_document FOREIGN KEY (workspace_id, document_id)
        REFERENCES edu.documents(workspace_id, id),
      CONSTRAINT ck_document_versions_failed CHECK ((status = 'failed') = (error_code IS NOT NULL)),
      CONSTRAINT ck_document_versions_ready CHECK (
        status IN ('processing','failed') OR (text_sha256 IS NOT NULL AND activated_at IS NOT NULL)
      )
    );
    -- Activation invariant: at most one active version per document.
    CREATE UNIQUE INDEX uq_document_versions_active
      ON edu.document_versions(document_id) WHERE status = 'active';
    CREATE INDEX ix_document_versions_history
      ON edu.document_versions(workspace_id, document_id, version_no DESC);

    ALTER TABLE edu.documents ADD CONSTRAINT fk_documents_active_version
      FOREIGN KEY (workspace_id, id, active_version_id)
      REFERENCES edu.document_versions(workspace_id, document_id, id)
      DEFERRABLE INITIALLY DEFERRED;

    CREATE TABLE edu.document_chunks (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      document_version_id uuid NOT NULL,
      chunk_index integer NOT NULL CHECK (chunk_index >= 0),
      page_no integer CHECK (page_no IS NULL OR page_no >= 1),
      section_path text CHECK (section_path IS NULL OR length(section_path) <= 1000),
      char_start integer NOT NULL CHECK (char_start >= 0),
      char_end integer NOT NULL,
      text text NOT NULL CHECK (length(text) > 0),
      text_sha256 bytea NOT NULL CHECK (octet_length(text_sha256) = 32),
      token_estimate integer NOT NULL CHECK (token_estimate >= 0),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CONSTRAINT uq_document_chunks_index UNIQUE (document_version_id, chunk_index),
      CONSTRAINT fk_document_chunks_version FOREIGN KEY (workspace_id, document_version_id)
        REFERENCES edu.document_versions(workspace_id, id),
      CONSTRAINT ck_document_chunks_span CHECK (char_end > char_start)
    );

    CREATE TABLE edu.document_curriculum_tags (
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      document_id uuid NOT NULL,
      curriculum_unit_id uuid NOT NULL REFERENCES edu.curriculum_units(id),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY (document_id, curriculum_unit_id),
      CONSTRAINT fk_document_curriculum_tags_document FOREIGN KEY (workspace_id, document_id)
        REFERENCES edu.documents(workspace_id, id)
    );
    CREATE INDEX ix_document_curriculum_tags_unit
      ON edu.document_curriculum_tags(workspace_id, curriculum_unit_id);
    """)

    # Immutability guards (invoker triggers; they run under the caller's RLS context).
    op.execute("""
    CREATE FUNCTION edu.document_version_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
      BEGIN
        IF (NEW.id, NEW.workspace_id, NEW.document_id, NEW.version_no, NEW.created_at)
           IS DISTINCT FROM
           (OLD.id, OLD.workspace_id, OLD.document_id, OLD.version_no, OLD.created_at) THEN
          RAISE EXCEPTION 'document version identity is immutable'
            USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status <> 'processing' AND
           (NEW.parser, NEW.parser_version, NEW.chunker_version, NEW.page_count, NEW.char_count,
            NEW.chunk_count, NEW.text_sha256, NEW.error_code, NEW.activated_at)
           IS DISTINCT FROM
           (OLD.parser, OLD.parser_version, OLD.chunker_version, OLD.page_count, OLD.char_count,
            OLD.chunk_count, OLD.text_sha256, OLD.error_code, OLD.activated_at) THEN
          RAISE EXCEPTION 'finished document version is immutable'
            USING ERRCODE = 'check_violation';
        END IF;
        IF NOT (NEW.status = OLD.status
                OR (OLD.status = 'processing' AND NEW.status IN ('active','failed'))
                OR (OLD.status = 'active' AND NEW.status = 'superseded')) THEN
          RAISE EXCEPTION 'invalid document version transition'
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END $$;
    CREATE TRIGGER document_version_guard BEFORE UPDATE ON edu.document_versions
      FOR EACH ROW EXECUTE FUNCTION edu.document_version_guard();

    CREATE FUNCTION edu.document_chunk_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
      BEGIN
        IF NOT EXISTS (SELECT 1 FROM edu.document_versions v
                       WHERE v.id = NEW.document_version_id
                         AND v.workspace_id = NEW.workspace_id
                         AND v.status = 'processing') THEN
          RAISE EXCEPTION 'chunks can only be added to a processing version'
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END $$;
    CREATE TRIGGER document_chunk_guard BEFORE INSERT ON edu.document_chunks
      FOR EACH ROW EXECUTE FUNCTION edu.document_chunk_guard();

    REVOKE ALL ON FUNCTION edu.document_version_guard(), edu.document_chunk_guard()
      FROM PUBLIC;
    """)

    for table in CATALOG_TABLES:
        op.execute(f"""
        ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_read ON edu.{table} FOR SELECT USING (true);
        """)

    for table in TENANT_TABLES:
        op.execute(f"""
        ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY {table}_tenant ON edu.{table} FOR ALL
          USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
        """)

    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduvia_runtime') THEN
        -- Default privileges grant more; replace them with the exact lean set.
        REVOKE ALL ON edu.curriculum_subjects, edu.curriculum_units, edu.document_versions,
          edu.document_chunks, edu.document_curriculum_tags FROM eduvia_runtime;
        -- Curriculum is platform metadata: read-only for the runtime role.
        GRANT SELECT ON edu.curriculum_subjects, edu.curriculum_units TO eduvia_runtime;
        GRANT SELECT, INSERT, UPDATE ON edu.document_versions TO eduvia_runtime;
        -- Chunks are immutable once written.
        GRANT SELECT, INSERT ON edu.document_chunks TO eduvia_runtime;
        -- Tags are a replaceable association set (PUT replaces the whole set).
        GRANT SELECT, INSERT, DELETE ON edu.document_curriculum_tags TO eduvia_runtime;
      END IF;
    END $$;
    """)


def downgrade():
    raise RuntimeError("Knowledge migration is forward-only; restore a reviewed backup instead")
