"""Static checks of the 0011 knowledge migration SQL and model drift (no database)."""

import importlib.util
import re
from pathlib import Path

import pytest

from app.infrastructure.database import Base
from app.models import documents, knowledge  # noqa: F401

PATH = Path(__file__).parents[1] / "migrations" / "versions" / "0011_knowledge.py"
TENANT_TABLES = ("document_versions", "document_chunks", "document_curriculum_tags")
CATALOG_TABLES = ("curriculum_subjects", "curriculum_units")


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("migration_0007", PATH)
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


def create_body(sql: str, table: str) -> str:
    match = re.search(rf"CREATE TABLE edu\.{table} \((.*?)\); (?:CREATE|ALTER)", sql)
    assert match, table
    return match.group(1)


def test_revision_chain(migration):
    assert migration.revision == "0011_knowledge"
    assert migration.down_revision == "0010_jobs_storage"
    with pytest.raises(RuntimeError):
        migration.downgrade()


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_tenant_tables_force_rls_and_policy(sql, table):
    assert f"ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY" in sql
    assert f"ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY" in sql
    policy = re.search(rf"CREATE POLICY {table}_tenant ON edu\.{table} FOR ALL (.*?);", sql)
    assert policy, table
    body = policy.group(1)
    assert body.count("current_setting('edu.current_workspace_id', true)") == 2
    assert body.count("edu.can_read_workspace(workspace_id)") == 2
    assert "workspace_id uuid NOT NULL REFERENCES edu.workspaces(id)" in create_body(sql, table)


@pytest.mark.parametrize("table", CATALOG_TABLES)
def test_catalog_tables_are_read_only_metadata(sql, table):
    assert f"ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY" in sql
    assert f"ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY" in sql
    assert f"CREATE POLICY {table}_read ON edu.{table} FOR SELECT USING (true)" in sql
    assert not re.search(rf"CREATE POLICY \w+ ON edu\.{table} FOR (ALL|INSERT|UPDATE|DELETE)", sql)
    assert "workspace_id" not in create_body(sql, table)


def test_composite_tenant_foreign_keys(sql):
    assert (
        "FOREIGN KEY (workspace_id, document_id) REFERENCES edu.documents(workspace_id, id)"
        in create_body(sql, "document_versions")
    )
    assert (
        "FOREIGN KEY (workspace_id, document_version_id) "
        "REFERENCES edu.document_versions(workspace_id, id)" in create_body(sql, "document_chunks")
    )
    assert "REFERENCES edu.documents(workspace_id, id)" in create_body(
        sql, "document_curriculum_tags"
    )
    assert (
        "FOREIGN KEY (workspace_id, id, active_version_id) "
        "REFERENCES edu.document_versions(workspace_id, document_id, id) "
        "DEFERRABLE INITIALLY DEFERRED" in sql
    )
    assert "ADD CONSTRAINT uq_documents_workspace_id UNIQUE (workspace_id, id)" in sql


def test_activation_invariant_and_immutability(sql):
    assert (
        "CREATE UNIQUE INDEX uq_document_versions_active ON edu.document_versions(document_id) "
        "WHERE status = 'active'" in sql
    )
    assert "UNIQUE (document_id, version_no)" in sql
    assert "UNIQUE (document_version_id, chunk_index)" in sql
    assert "CHECK ((status = 'failed') = (error_code IS NOT NULL))" in sql
    assert "BEFORE UPDATE ON edu.document_versions" in sql
    assert "BEFORE INSERT ON edu.document_chunks" in sql
    assert "OLD.status = 'processing' AND NEW.status IN ('active','failed')" in sql
    assert "OLD.status = 'active' AND NEW.status = 'superseded'" in sql
    assert "FROM PUBLIC" in sql
    assert "SECURITY DEFINER" not in sql  # guards run as the invoker, under its RLS context
    assert "vector" not in sql.lower()  # embeddings get their own migration (KNOW-06)


def test_rights_scope_is_private_only(sql):
    assert "ADD COLUMN rights_scope text NOT NULL DEFAULT 'private'" in sql
    assert "CHECK (rights_scope IN ('private'))" in sql
    assert "CHECK (active_version_id IS NULL OR rights_attested)" in sql


def test_runtime_grants_are_least_privilege(sql):
    assert "IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduvia_runtime')" in sql
    assert "GRANT SELECT ON edu.curriculum_subjects, edu.curriculum_units TO eduvia_runtime" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON edu.document_versions TO eduvia_runtime" in sql
    assert "GRANT SELECT, INSERT ON edu.document_chunks TO eduvia_runtime" in sql
    assert "GRANT SELECT, INSERT, DELETE ON edu.document_curriculum_tags TO eduvia_runtime" in sql
    for table in ("curriculum_subjects", "curriculum_units", "document_versions"):
        assert not re.search(rf"GRANT[^;]*DELETE[^;]*edu\.{table}\b", sql), table
    assert not re.search(r"GRANT[^;]*UPDATE[^;]*edu\.document_chunks", sql)
    assert not re.search(r"GRANT[^;]*(INSERT|UPDATE)[^;]*edu\.curriculum_", sql)


def test_seed_is_stable_and_marked_as_draft(migration, sql):
    assert len(migration.TOAN_UNITS) == 15
    assert {grade for grade, _, _ in migration.TOAN_UNITS} == {10, 11, 12}
    assert {code for code, _ in migration.SUBJECTS} == {"toan", "ngu-van", "tieng-anh"}
    assert sql.count("'seed:pilot-draft'") == 15
    assert migration.subject_id("toan") == migration.subject_id("toan")
    assert str(migration.unit_id("toan", 10, "2018", "T10-01")) in sql
    assert len({code for _, code, _ in migration.TOAN_UNITS}) == 15


@pytest.mark.parametrize(
    "table,columns",
    [
        (
            "curriculum_units",
            "id subject_id grade program_year unit_code title_vi parent_id sort_order "
            "source_provenance version created_at",
        ),
        (
            "document_versions",
            "id workspace_id document_id version_no status parser parser_version "
            "chunker_version page_count char_count chunk_count text_sha256 error_code "
            "created_at activated_at",
        ),
        (
            "document_chunks",
            "id workspace_id document_version_id chunk_index page_no section_path char_start "
            "char_end text text_sha256 token_estimate created_at",
        ),
        ("document_curriculum_tags", "workspace_id document_id curriculum_unit_id created_at"),
    ],
)
def test_models_match_migration_columns(sql, table, columns):
    model = Base.metadata.tables[f"edu.{table}"]
    assert [c.name for c in model.columns] == columns.split()
    body = create_body(sql, table)
    for column in columns.split():
        assert re.search(rf"(^\s*|, ){column} ", body), (table, column)


def test_document_model_has_new_columns():
    names = {c.name for c in Base.metadata.tables["edu.documents"].columns}
    assert {"rights_scope", "active_version_id"} <= names
