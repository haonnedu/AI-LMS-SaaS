"""Cheap drift guard for migration 0008 (no database)."""

import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0008_classes.py"


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("migration_0008_classes", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def full_sql(module) -> str:
    return "\n".join(
        [module.TABLES_SQL, module.FUNCTIONS_SQL, module.RUNTIME_GRANTS_SQL]
        + [module.tenant_rls(table) for table in module.TABLES]
    )


def test_revision_chain(migration):
    assert migration.revision == "0008_classes"
    assert migration.down_revision == "0007_auth_revocation"


@pytest.mark.parametrize(
    "table", ["classes", "class_teachers", "students", "enrollments", "class_invitations"]
)
def test_every_table_forces_rls_with_all_policies(migration, table):
    sql = full_sql(migration)
    assert f"CREATE TABLE edu.{table} (" in sql
    assert "workspace_id uuid NOT NULL REFERENCES edu.workspaces(id)" in sql
    assert f"ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY" in sql
    assert f"ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY" in sql
    for action in ("select", "insert", "update", "delete"):
        assert f"CREATE POLICY {table}_tenant_{action} ON edu.{table}" in sql
    assert f"edu.{table}" in migration.RUNTIME_GRANTS_SQL


def test_policies_require_context_and_membership(migration):
    assert "current_setting('edu.current_workspace_id', true)" in migration.TENANT_PREDICATE
    assert "edu.can_read_workspace(workspace_id)" in migration.TENANT_PREDICATE


def test_definer_functions_are_owned_and_not_public(migration):
    sql = migration.FUNCTIONS_SQL
    for signature in ("accept_class_invitation(bytea)", "workspace_staff_role(uuid, uuid)"):
        assert f"ALTER FUNCTION edu.{signature} OWNER TO eduvia_identity_owner" in sql
    assert "FROM PUBLIC" in sql
    assert "SET search_path=pg_catalog,edu" in sql
    assert "FOR UPDATE" in sql
    assert sql.rstrip().endswith("REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner;")
    assert "IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduvia_runtime')" in (
        migration.RUNTIME_GRANTS_SQL
    )


def test_token_hash_only(migration):
    assert "token_hash bytea NOT NULL" in migration.TABLES_SQL
    assert "octet_length(token_hash) = 32" in migration.TABLES_SQL
    assert " token text" not in migration.TABLES_SQL
