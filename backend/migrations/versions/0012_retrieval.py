"""M3 retrieval (KNOW-06..09): lexical + vector columns on chunks, embedding runs, and the
narrow deletion helper used by ``document.delete`` jobs.

* ``document_chunks.search_vector`` is a STORED generated column over ``to_tsvector('simple',
  text)``: PostgreSQL ships no Vietnamese stemmer, so the ``simple`` config (lower-casing, no
  stemming, no stop words) is the honest baseline. Being generated, the runtime role can never
  write a forged lexical index. GIN index for ``@@`` matches.
* ``document_chunks.embedding vector(EMBEDDING_DIMENSION)`` plus ``embedding_model`` /
  ``embedding_version``: written once per (model, version) by the embedding stage. Retrieval
  ignores vectors whose model/version differ from the configured provider, so incompatible
  vectors are never mixed. Changing ``EMBEDDING_DIMENSION`` requires a NEW migration (parallel
  column or ALTER TYPE after clearing vectors) and a full re-embed; never edit it here.
* No HNSW/IVFFlat index yet: the pilot corpus is small and an exact scan *inside the authorized
  subset* has perfect filtered recall. ANN indexes post-filter and can return too few authorized
  rows (DATABASE.md section 5); add one only after measuring corpus size and filtered recall.
* Chunks stay immutable except for the three embedding columns: a BEFORE UPDATE guard rejects
  any other change, and the runtime role only gets column-level UPDATE on those columns.
* ``embedding_runs``: tenant table (FORCE RLS) recording each embedding attempt, its metered
  units and provider request IDs (never texts).
* ``edu.purge_document_chunks(document_id)``: SECURITY DEFINER, owned by the NOLOGIN
  ``eduvia_identity_owner``. The caller must be inside the document's workspace context with an
  active membership, and the document must already be soft-deleted. It deletes the chunks and
  marks finished versions ``withdrawn`` (new terminal status), so the runtime role never needs
  DELETE on chunks. RLS still applies inside the function (the owner role has no policy bypass).
"""

from alembic import op

revision = "0012_retrieval"
down_revision = "0011_knowledge"
branch_labels = None
depends_on = None

# Must equal app.models.knowledge.EMBEDDING_DIMENSION and Settings.embedding_dimension.
EMBEDDING_DIMENSION = 1024

TENANT_PREDICATE = (
    "workspace_id::text = current_setting('edu.current_workspace_id', true) "
    "AND edu.can_read_workspace(workspace_id)"
)


def upgrade():
    op.execute(f"""
    ALTER TABLE edu.document_chunks
      ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, text)) STORED,
      ADD COLUMN embedding public.vector({EMBEDDING_DIMENSION}),
      ADD COLUMN embedding_model text
        CHECK (embedding_model IS NULL OR length(embedding_model) BETWEEN 1 AND 128),
      ADD COLUMN embedding_version text
        CHECK (embedding_version IS NULL OR length(embedding_version) BETWEEN 1 AND 64),
      ADD CONSTRAINT ck_document_chunks_embedding_identity CHECK (
        (embedding IS NULL) = (embedding_model IS NULL)
        AND (embedding IS NULL) = (embedding_version IS NULL)
      );
    CREATE INDEX ix_document_chunks_search_vector
      ON edu.document_chunks USING gin (search_vector);
    CREATE INDEX ix_document_chunks_version
      ON edu.document_chunks(workspace_id, document_version_id);
    CREATE INDEX ix_document_versions_status
      ON edu.document_versions(workspace_id, status);
    """)

    # 'withdrawn' is terminal: purged versions can never be re-activated by a replay.
    op.execute("""
    DO $$ DECLARE c text; BEGIN
      FOR c IN SELECT conname FROM pg_constraint
               WHERE conrelid = 'edu.document_versions'::regclass AND contype = 'c'
                 AND pg_get_constraintdef(oid) LIKE '%superseded%' LOOP
        EXECUTE format('ALTER TABLE edu.document_versions DROP CONSTRAINT %I', c);
      END LOOP;
    END $$;
    ALTER TABLE edu.document_versions ADD CONSTRAINT ck_document_versions_status
      CHECK (status IN ('processing','active','failed','superseded','withdrawn'));

    CREATE OR REPLACE FUNCTION edu.document_version_guard() RETURNS trigger
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
                OR (OLD.status = 'active' AND NEW.status = 'superseded')
                OR (OLD.status IN ('active','superseded') AND NEW.status = 'withdrawn')) THEN
          RAISE EXCEPTION 'invalid document version transition'
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END $$;

    -- Chunks are immutable except for writing the embedding triple.
    CREATE FUNCTION edu.document_chunk_update_guard() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,edu AS $$
      BEGIN
        IF (NEW.id, NEW.workspace_id, NEW.document_version_id, NEW.chunk_index, NEW.page_no,
            NEW.section_path, NEW.char_start, NEW.char_end, NEW.text, NEW.text_sha256,
            NEW.token_estimate, NEW.created_at)
           IS DISTINCT FROM
           (OLD.id, OLD.workspace_id, OLD.document_version_id, OLD.chunk_index, OLD.page_no,
            OLD.section_path, OLD.char_start, OLD.char_end, OLD.text, OLD.text_sha256,
            OLD.token_estimate, OLD.created_at) THEN
          RAISE EXCEPTION 'document chunks are immutable except for embeddings'
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END $$;
    CREATE TRIGGER document_chunk_update_guard BEFORE UPDATE ON edu.document_chunks
      FOR EACH ROW EXECUTE FUNCTION edu.document_chunk_update_guard();
    REVOKE ALL ON FUNCTION edu.document_chunk_update_guard() FROM PUBLIC;
    """)

    op.execute(f"""
    CREATE TABLE edu.embedding_runs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      workspace_id uuid NOT NULL REFERENCES edu.workspaces(id),
      document_version_id uuid NOT NULL,
      job_id uuid,
      model text NOT NULL CHECK (length(model) BETWEEN 1 AND 128),
      version text NOT NULL CHECK (length(version) BETWEEN 1 AND 64),
      status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','succeeded','failed')),
      chunk_count integer NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
      units integer NOT NULL DEFAULT 0 CHECK (units >= 0),
      provider_request_ids jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(provider_request_ids) = 'array'),
      error_code text CHECK (error_code IS NULL OR length(error_code) BETWEEN 1 AND 64),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      finished_at timestamptz,
      CONSTRAINT fk_embedding_runs_version FOREIGN KEY (workspace_id, document_version_id)
        REFERENCES edu.document_versions(workspace_id, id),
      CONSTRAINT fk_embedding_runs_job FOREIGN KEY (workspace_id, job_id)
        REFERENCES edu.background_jobs(workspace_id, id),
      CONSTRAINT ck_embedding_runs_failed CHECK ((status = 'failed') = (error_code IS NOT NULL)),
      CONSTRAINT ck_embedding_runs_finished CHECK ((status = 'pending') = (finished_at IS NULL))
    );
    CREATE INDEX ix_embedding_runs_version
      ON edu.embedding_runs(workspace_id, document_version_id, created_at DESC);

    ALTER TABLE edu.embedding_runs ENABLE ROW LEVEL SECURITY;
    ALTER TABLE edu.embedding_runs FORCE ROW LEVEL SECURITY;
    CREATE POLICY embedding_runs_tenant ON edu.embedding_runs FOR ALL
      USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
    """)

    # The definer runs as eduvia_identity_owner WITHOUT a bypass policy: the existing tenant
    # policies (which apply to every role) still filter by the caller's workspace context.
    op.execute("""
    GRANT CREATE ON SCHEMA edu TO eduvia_identity_owner;
    GRANT SELECT ON edu.documents TO eduvia_identity_owner;
    GRANT SELECT, UPDATE (status) ON edu.document_versions TO eduvia_identity_owner;
    GRANT SELECT, DELETE ON edu.document_chunks TO eduvia_identity_owner;

    -- Errors: P0002 document not visible in the caller's workspace, EV003 not soft-deleted.
    CREATE FUNCTION edu.purge_document_chunks(p_document_id uuid) RETURNS integer
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,edu AS $$
      DECLARE
        ws uuid;
        doc_status text;
        purged integer;
      BEGIN
        SELECT d.workspace_id, d.status INTO ws, doc_status
          FROM edu.documents d WHERE d.id = p_document_id;
        IF ws IS NULL
           OR ws::text IS DISTINCT FROM current_setting('edu.current_workspace_id', true)
           OR NOT edu.can_read_workspace(ws) THEN
          RAISE EXCEPTION 'Document not found' USING ERRCODE = 'P0002';
        END IF;
        IF doc_status <> 'deleted' THEN
          RAISE EXCEPTION 'Document is not deleted' USING ERRCODE = 'EV003';
        END IF;
        DELETE FROM edu.document_chunks c
          WHERE c.workspace_id = ws
            AND c.document_version_id IN (
              SELECT v.id FROM edu.document_versions v
              WHERE v.workspace_id = ws AND v.document_id = p_document_id);
        GET DIAGNOSTICS purged = ROW_COUNT;
        UPDATE edu.document_versions v SET status = 'withdrawn'
          WHERE v.workspace_id = ws AND v.document_id = p_document_id
            AND v.status IN ('active','superseded');
        RETURN purged;
      END $$;
    ALTER FUNCTION edu.purge_document_chunks(uuid) OWNER TO eduvia_identity_owner;
    REVOKE ALL ON FUNCTION edu.purge_document_chunks(uuid) FROM PUBLIC;
    REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner;

    DO $$ BEGIN
      IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduvia_runtime') THEN
        REVOKE ALL ON edu.embedding_runs FROM eduvia_runtime;
        GRANT SELECT, INSERT, UPDATE ON edu.embedding_runs TO eduvia_runtime;
        -- Column-level: only the embedding triple; text/identity stay read-only.
        GRANT UPDATE (embedding, embedding_model, embedding_version)
          ON edu.document_chunks TO eduvia_runtime;
        GRANT EXECUTE ON FUNCTION edu.purge_document_chunks(uuid) TO eduvia_runtime;
      END IF;
    END $$;
    """)


def downgrade():
    raise RuntimeError("Retrieval migration is forward-only; restore a reviewed backup instead")
