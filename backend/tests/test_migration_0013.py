"""Static checks of the 0013 authoring migration SQL and model drift (no database)."""

import importlib.util
import re
from pathlib import Path

import pytest

from app.infrastructure.database import Base
from app.models import authoring, documents, jobs, knowledge  # noqa: F401

PATH = Path(__file__).parents[1] / "migrations" / "versions" / "0013_authoring.py"
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


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("migration_0009", PATH)
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
    assert migration.revision == "0013_authoring"
    assert migration.down_revision == "0012_retrieval"
    with pytest.raises(RuntimeError):
        migration.downgrade()


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_every_table_is_tenant_scoped_with_force_rls(sql, table):
    assert f"ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY" in sql
    assert f"ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY" in sql
    policy = re.search(rf"CREATE POLICY {table}_tenant ON edu\.{table} FOR ALL (.*?);", sql)
    assert policy, table
    body = policy.group(1)
    assert body.count("current_setting('edu.current_workspace_id', true)") == 2
    assert body.count("edu.can_read_workspace(workspace_id)") == 2
    assert "workspace_id uuid NOT NULL REFERENCES edu.workspaces(id)" in create_body(sql, table)


@pytest.mark.parametrize(
    "table,column,parent",
    [
        ("content_revisions", "content_item_id", "content_items"),
        ("review_requests", "content_revision_id", "content_revisions"),
        ("question_revisions", "question_id", "questions"),
        ("question_keys", "question_revision_id", "question_revisions"),
        ("question_objectives", "question_id", "questions"),
        ("blueprint_versions", "blueprint_id", "blueprints"),
    ],
)
def test_composite_tenant_foreign_keys(sql, table, column, parent):
    fk = f"FOREIGN KEY (workspace_id, {column}) REFERENCES edu.{parent}(workspace_id, id)"
    assert fk in create_body(sql, table)


@pytest.mark.parametrize(
    "table", [t for t in TENANT_TABLES if t not in ("question_keys", "question_objectives")]
)
def test_workspace_id_unique_pairs(sql, table):
    assert f"CONSTRAINT uq_{table}_workspace_id UNIQUE (workspace_id, id)" in create_body(
        sql, table
    )


def test_current_pointers_are_deferred_composite_fks(sql):
    for column, target, parent in (
        ("current_revision_id", "content_revisions", "content_item_id"),
        ("current_revision_id", "question_revisions", "question_id"),
        ("current_version_id", "blueprint_versions", "blueprint_id"),
    ):
        assert (
            f"FOREIGN KEY (workspace_id, id, {column}) "
            f"REFERENCES edu.{target}(workspace_id, {parent}, id) DEFERRABLE INITIALLY DEFERRED"
        ) in sql


def test_question_keys_have_no_runtime_select(sql):
    grants = runtime_grants(sql)
    assert "GRANT INSERT ON edu.question_keys TO eduvia_runtime" in grants
    for grant in grants:
        if "question_keys" in grant:
            assert not re.search(r"\b(SELECT|UPDATE|DELETE|ALL)\b", grant.split(" ON ")[0]), grant
    # Default privileges are replaced first, so nothing implicit survives on the key table.
    assert re.search(r"REVOKE ALL ON [^;]*edu\.question_keys[^;]* FROM eduvia_runtime", sql)
    assert "GRANT SELECT ON edu.question_keys TO eduvia_identity_owner" in sql


def test_key_function_is_narrow_definer(sql):
    function = re.search(r"CREATE FUNCTION edu\.question_key\(p_revision_id uuid\) (.*?)\$\$;", sql)
    assert function
    body = function.group(1)
    assert "SECURITY DEFINER SET search_path=pg_catalog,edu" in body
    assert "current_setting('edu.current_workspace_id', true)" in body
    assert "edu.can_read_workspace(k.workspace_id)" in body
    assert "m.user_id = edu.actor_id()" in body
    assert "m.role IN ('owner','admin','teacher')" in body
    assert "ALTER FUNCTION edu.question_key(uuid) OWNER TO eduvia_identity_owner" in sql
    assert (
        "REVOKE ALL ON FUNCTION edu.question_key(uuid), edu.workspace_staff_count(uuid) FROM PUBLIC"
        in sql
    )
    assert (
        "CREATE POLICY question_keys_key_function ON edu.question_keys FOR SELECT "
        "TO eduvia_identity_owner" in sql
    )
    assert sql.count("GRANT CREATE ON SCHEMA edu TO eduvia_identity_owner") == sql.count(
        "REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner"
    )


def test_least_privilege_grants(sql):
    grants = runtime_grants(sql)
    deletes = [g for g in grants if "DELETE" in g.split(" ON ")[0]]
    assert deletes == ["GRANT SELECT, INSERT, DELETE ON edu.question_objectives TO eduvia_runtime"]
    assert "GRANT SELECT, INSERT ON edu.question_revisions TO eduvia_runtime" in grants
    assert not any("question_revisions" in g and "UPDATE" in g for g in grants)


def test_item_type_is_check_constrained_and_extendable(sql):
    body = create_body(sql, "questions")
    assert (
        "item_type text NOT NULL DEFAULT 'single_choice' CHECK (item_type IN ('single_choice'))"
        in body
    )
    assert "jsonb_array_length(choices) BETWEEN 3 AND 5" in create_body(sql, "question_revisions")
    assert "correct_key char(1) NOT NULL CHECK (correct_key IN ('A','B','C','D','E'))" in sql


def test_immutability_triggers(sql):
    assert "BEFORE INSERT OR UPDATE ON edu.content_revisions" in sql
    assert "OLD.status <> 'draft' AND (NEW.body, NEW.body_sha256, NEW.audience)" in sql
    assert "OLD.status = 'draft' AND NEW.status = 'in_review'" in sql
    assert "OLD.status = 'in_review' AND NEW.status = 'approved'" in sql
    assert "OLD.status = 'approved' AND NEW.status = 'published'" in sql
    assert "OLD.status <> 'archived' AND NEW.status = 'archived'" in sql
    assert "BEFORE UPDATE ON edu.blueprint_versions" in sql
    assert "published blueprint version is immutable" in sql
    assert "BEFORE INSERT ON edu.question_keys" in sql
    assert "BEFORE UPDATE ON edu.questions" in sql
    assert "CHECK (origin_kind IN ('teacher_defined'))" in sql
    assert "octet_length(body::text) <= 204800" in sql


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_models_match_migration_columns(sql, table):
    model = Base.metadata.tables[f"edu.{table}"]
    body = create_body(sql, table)
    for column in model.columns:
        assert re.search(rf"(^\s*|, ){column.name} ", body), (table, column.name)
    declared = re.findall(
        r"(?:^\s*|, )([a-z_0-9]+) "
        r"(?:uuid|text|integer|smallint|jsonb|bytea|timestamptz|numeric|char)",
        body,
    )
    assert sorted(declared) == sorted(c.name for c in model.columns), table
