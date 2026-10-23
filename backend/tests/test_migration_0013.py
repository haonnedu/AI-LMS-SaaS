"""Static checks of the 0013 generation/exam/export migration SQL and model drift (no DB)."""

import importlib.util
import re
from pathlib import Path

import pytest

from app.infrastructure.database import Base
from app.models import authoring, documents, generation, jobs, knowledge  # noqa: F401

PATH = Path(__file__).parents[1] / "migrations" / "versions" / "0013_generation_exams.py"
TENANT_TABLES = (
    "generation_jobs",
    "generation_sources",
    "exams",
    "exam_versions",
    "exam_items",
    "exam_answer_keys",
    "export_jobs",
)


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("migration_0010", PATH)
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


def runtime_grants(sql: str) -> list[str]:
    block = re.search(r"rolname = 'eduvia_runtime'\) THEN (.*?) END IF;", sql)
    assert block
    return re.findall(r"GRANT [^;]*? TO eduvia_runtime", block.group(1))


def test_revision_chain(migration):
    assert migration.revision == "0013_generation_exams"
    assert migration.down_revision == "0012_authoring"
    with pytest.raises(RuntimeError):
        migration.downgrade()


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_every_table_is_tenant_scoped_with_force_rls(sql, table):
    assert f"ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY" in sql
    assert f"ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY" in sql
    policy = re.search(rf"CREATE POLICY {table}_tenant ON edu\.{table} FOR ALL (.*?);", sql)
    assert policy, table
    assert policy.group(1).count("current_setting('edu.current_workspace_id', true)") == 2
    assert policy.group(1).count("edu.can_read_workspace(workspace_id)") == 2
    assert "workspace_id uuid NOT NULL REFERENCES edu.workspaces(id)" in create_body(sql, table)


@pytest.mark.parametrize(
    "table,columns,parent",
    [
        ("generation_jobs", "background_job_id", "background_jobs(workspace_id, id)"),
        ("generation_sources", "generation_job_id", "generation_jobs(workspace_id, id)"),
        ("exam_versions", "exam_id", "exams(workspace_id, id)"),
        ("exam_items", "exam_version_id", "exam_versions(workspace_id, id)"),
        (
            "exam_answer_keys",
            "exam_version_id, exam_item_id",
            "exam_items(workspace_id, exam_version_id, id)",
        ),
        ("export_jobs", "exam_version_id", "exam_versions(workspace_id, id)"),
        ("export_jobs", "content_revision_id", "content_revisions(workspace_id, id)"),
    ],
)
def test_composite_tenant_foreign_keys(sql, table, columns, parent):
    assert f"FOREIGN KEY (workspace_id, {columns}) REFERENCES edu.{parent}" in create_body(
        sql, table
    )


def test_exact_shape_contract_for_assessment(sql):
    assert "CONSTRAINT uq_exam_versions_number UNIQUE (exam_id, version_no)" in sql
    assert "CONSTRAINT uq_exam_versions_workspace_id UNIQUE (workspace_id, id)" in sql
    assert "CONSTRAINT uq_exam_items_position UNIQUE (exam_version_id, position)" in sql
    assert "CONSTRAINT uq_exam_items_workspace_id UNIQUE (workspace_id, id)" in sql
    assert "CONSTRAINT uq_generation_sources_rank UNIQUE (generation_job_id, rank)" in sql
    assert "CONSTRAINT uq_generation_jobs_background_job UNIQUE (background_job_id)" in sql
    assert "num_nonnulls(content_revision_id, exam_version_id) = 1" in sql
    assert (
        "FOREIGN KEY (workspace_id, id, current_version_id) REFERENCES "
        "edu.exam_versions(workspace_id, exam_id, id) DEFERRABLE INITIALLY DEFERRED"
    ) in sql
    assert "chunk_id uuid REFERENCES edu.document_chunks(id) ON DELETE SET NULL" in sql


def test_exam_answer_keys_have_no_runtime_select(sql):
    grants = runtime_grants(sql)
    assert "GRANT INSERT ON edu.exam_answer_keys TO eduvia_runtime" in grants
    for grant in grants:
        if "exam_answer_keys" in grant:
            assert not re.search(r"\b(SELECT|UPDATE|DELETE|ALL)\b", grant.split(" ON ")[0]), grant
    assert re.search(r"REVOKE ALL ON [^;]*edu\.exam_answer_keys[^;]* FROM eduvia_runtime", sql)
    assert not any("DELETE" in g.split(" ON ")[0] for g in grants)
    assert "GRANT SELECT, INSERT ON edu.generation_sources, edu.exam_items TO eduvia_runtime" in (
        grants
    )


@pytest.mark.parametrize(
    "name,signature",
    [
        ("exam_item_key", "p_item_id uuid"),
        ("exam_item_explanation", "p_item_id uuid"),
        ("exam_keys_for_scoring", "p_exam_version_id uuid"),
        ("exam_version_publish_error", "p_exam_version_id uuid"),
    ],
)
def test_definer_functions_are_narrow(sql, name, signature):
    function = re.search(rf"CREATE FUNCTION edu\.{name}\({signature}\) (.*?)\$\$;", sql)
    assert function, name
    body = function.group(1)
    assert "SECURITY DEFINER SET search_path=pg_catalog,edu" in body
    assert "current_setting('edu.current_workspace_id', true)" in body
    assert "edu.can_read_workspace(" in body
    assert f"ALTER FUNCTION edu.{name}(uuid) OWNER TO eduvia_identity_owner" in sql
    assert re.search(rf"REVOKE ALL ON FUNCTION [^;]*edu\.{name}\(uuid\)[^;]* FROM PUBLIC", sql)
    assert re.search(
        rf"GRANT EXECUTE ON FUNCTION [^;]*edu\.{name}\(uuid\)[^;]* TO eduvia_runtime", sql
    )


def test_key_readers_require_teacher_roles_and_scoring_requires_publication(sql):
    for name in ("exam_item_key", "exam_item_explanation"):
        body = re.search(rf"CREATE FUNCTION edu\.{name}\(.*?\$\$;", sql).group(0)
        assert "m.user_id = edu.actor_id()" in body
        assert "m.role IN ('owner','admin','teacher')" in body
    scoring = re.search(r"CREATE FUNCTION edu\.exam_keys_for_scoring\(.*?END \$\$;", sql).group(0)
    assert "IF published IS NULL THEN" in scoring and "ERRCODE = '42501'" in scoring
    assert "RETURNS TABLE(exam_item_id uuid, correct_key char, points numeric)" in scoring
    assert sql.count("GRANT CREATE ON SCHEMA edu TO eduvia_identity_owner") == sql.count(
        "REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner"
    )


def test_immutability_and_publication_triggers(sql):
    assert "BEFORE INSERT OR UPDATE OR DELETE ON edu.exam_versions" in sql
    assert "published exam version is immutable" in sql
    assert "problem := edu.exam_version_publish_error(NEW.id)" in sql
    for table in ("exam_items", "exam_answer_keys"):
        assert f"BEFORE INSERT OR UPDATE OR DELETE ON edu.{table}" in sql
    assert "exam version snapshot is immutable" in sql
    assert "BEFORE INSERT ON edu.exam_answer_keys" in sql
    for rule in ("exam_empty", "invalid_choices", "invalid_points", "missing_key", "invalid_key"):
        assert f"'{rule}'" in sql
    assert "'points_mismatch'" in sql
    assert "BEFORE UPDATE ON edu.generation_jobs" in sql
    assert "BEFORE UPDATE ON edu.export_jobs" in sql


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_models_match_migration_columns(sql, table):
    model = Base.metadata.tables[f"edu.{table}"]
    body = create_body(sql, table)
    declared = re.findall(
        r"(?:^\s*|, )([a-z_0-9]+) "
        r"(?:uuid|text|integer|smallint|bigint|jsonb|bytea|timestamptz|numeric|char)\b",
        body,
    )
    assert sorted(declared) == sorted(c.name for c in model.columns), table
