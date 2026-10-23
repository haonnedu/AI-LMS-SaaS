"""Static checks of the 0008 retrieval migration SQL and model drift (no database)."""

import importlib.util
import re
from pathlib import Path

import pytest

from app.core.config import Settings
from app.infrastructure.database import Base
from app.models import knowledge
from app.services import embeddings

PATH = Path(__file__).parents[1] / "migrations" / "versions" / "0008_retrieval.py"


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("migration_0008", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sql(migration):
    statements = []

    class FakeOp:
        def execute(self, statement):
            statements.append(str(statement))

    original = migration.op
    migration.op = FakeOp()
    try:
        migration.upgrade()
    finally:
        migration.op = original
    return re.sub(r"\s+", " ", "\n".join(statements))


def test_revision_chain_and_forward_only(migration):
    assert migration.revision == "0008_retrieval"
    assert migration.down_revision == "0007_knowledge"
    with pytest.raises(RuntimeError):
        migration.downgrade()


def test_dimension_is_consistent_everywhere(migration, sql):
    assert migration.EMBEDDING_DIMENSION == 1024
    assert knowledge.EMBEDDING_DIMENSION == migration.EMBEDDING_DIMENSION
    assert embeddings.EMBEDDING_DIMENSION == migration.EMBEDDING_DIMENSION
    assert Settings(_env_file=None).embedding_dimension == migration.EMBEDDING_DIMENSION
    assert "ADD COLUMN embedding public.vector(1024)" in sql
    with pytest.raises(ValueError):
        Settings(_env_file=None, embedding_dimension=1536)


def test_lexical_column_is_generated_with_simple_config_and_gin(sql):
    assert (
        "ADD COLUMN search_vector tsvector GENERATED ALWAYS AS "
        "(to_tsvector('simple'::regconfig, text)) STORED" in sql
    )
    assert "CREATE INDEX ix_document_chunks_search_vector ON edu.document_chunks USING gin" in sql
    # Exact scan for the pilot: no ANN index that could post-filter authorized rows away.
    assert not re.search(r"USING (hnsw|ivfflat)", sql, re.IGNORECASE)


def test_embedding_identity_triple_and_chunk_update_guard(sql):
    assert "ck_document_chunks_embedding_identity" in sql
    assert "BEFORE UPDATE ON edu.document_chunks" in sql
    guard = re.search(r"FUNCTION edu\.document_chunk_update_guard\(\)(.*?)END \$\$", sql)
    assert guard
    body = guard.group(1)
    for column in ("text", "text_sha256", "document_version_id", "chunk_index", "page_no"):
        assert f"NEW.{column}" in body and f"OLD.{column}" in body
    assert "NEW.embedding" not in body  # the embedding triple is the only mutable part


def test_withdrawn_status_is_terminal(sql):
    assert "CHECK (status IN ('processing','active','failed','superseded','withdrawn'))" in sql
    assert "OLD.status IN ('active','superseded') AND NEW.status = 'withdrawn'" in sql
    assert "OLD.status = 'processing' AND NEW.status IN ('active','failed')" in sql
    assert "withdrawn" in knowledge.VERSION_STATUSES
    assert not re.search(r"OLD\.status = 'withdrawn'", sql)


def test_embedding_runs_force_rls_and_composite_keys(sql):
    assert "ALTER TABLE edu.embedding_runs ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE edu.embedding_runs FORCE ROW LEVEL SECURITY" in sql
    policy = re.search(
        r"CREATE POLICY embedding_runs_tenant ON edu\.embedding_runs FOR ALL (.*?);", sql
    )
    assert policy
    assert policy.group(1).count("current_setting('edu.current_workspace_id', true)") == 2
    assert policy.group(1).count("edu.can_read_workspace(workspace_id)") == 2
    assert (
        "FOREIGN KEY (workspace_id, document_version_id) "
        "REFERENCES edu.document_versions(workspace_id, id)" in sql
    )
    assert "CHECK (status IN ('pending','succeeded','failed'))" in sql
    assert "CHECK ((status = 'failed') = (error_code IS NOT NULL))" in sql


def test_purge_function_is_narrow_security_definer(sql):
    function = re.search(
        r"CREATE FUNCTION edu\.purge_document_chunks\(p_document_id uuid\)(.*?)END \$\$", sql
    )
    assert function
    body = function.group(1)
    assert "RETURNS integer" in body
    assert "SECURITY DEFINER SET search_path=pg_catalog,edu" in body
    assert "current_setting('edu.current_workspace_id', true)" in body
    assert "edu.can_read_workspace(ws)" in body
    assert "doc_status <> 'deleted'" in body
    assert "DELETE FROM edu.document_chunks" in body
    assert "SET status = 'withdrawn'" in body
    assert "EXECUTE" not in body  # no dynamic SQL
    assert "ALTER FUNCTION edu.purge_document_chunks(uuid) OWNER TO eduvia_identity_owner" in sql
    assert "REVOKE ALL ON FUNCTION edu.purge_document_chunks(uuid) FROM PUBLIC" in sql
    assert "REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner" in sql
    # No bypass policy for the definer role: tenant policies keep applying inside it.
    assert not re.search(r"CREATE POLICY \w+ ON edu\.\w+ (FOR \w+ )?TO eduvia_identity_owner", sql)


def test_runtime_grants_are_least_privilege(sql):
    assert "IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduvia_runtime')" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON edu.embedding_runs TO eduvia_runtime" in sql
    assert (
        "GRANT UPDATE (embedding, embedding_model, embedding_version) "
        "ON edu.document_chunks TO eduvia_runtime" in sql
    )
    assert "GRANT EXECUTE ON FUNCTION edu.purge_document_chunks(uuid) TO eduvia_runtime" in sql
    assert not re.search(r"GRANT[^;]*DELETE[^;]*TO eduvia_runtime", sql)
    assert not re.search(r"GRANT UPDATE ON edu\.document_chunks", sql)


def test_embedding_run_model_matches_migration(sql):
    columns = (
        "id workspace_id document_version_id job_id model version status chunk_count units "
        "provider_request_ids error_code created_at finished_at"
    ).split()
    model = Base.metadata.tables["edu.embedding_runs"]
    assert [c.name for c in model.columns] == columns
    body = re.search(r"CREATE TABLE edu\.embedding_runs \((.*?)\); CREATE INDEX", sql).group(1)
    for column in columns:
        assert re.search(rf"(^\s*|, ){column} ", body), column
