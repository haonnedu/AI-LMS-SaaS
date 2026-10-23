"""Static checks of the 0006 migration SQL (no database)."""

import importlib.util
import re
from pathlib import Path

import pytest

PATH = Path(__file__).parents[1] / "migrations" / "versions" / "0006_jobs_storage.py"


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("migration_0006", PATH)
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


def test_revision_chain(migration):
    assert migration.revision == "0006_jobs_storage"
    assert migration.down_revision == "0005_classes"
    with pytest.raises(RuntimeError):
        migration.downgrade()


@pytest.mark.parametrize(
    "table", ["background_jobs", "usage_events", "workspace_quotas", "documents"]
)
def test_force_rls_and_tenant_policy(sql, table):
    assert f"CREATE TABLE edu.{table} (" in sql
    assert f"ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY" in sql
    assert f"ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY" in sql
    policy = re.search(rf"CREATE POLICY {table}_tenant ON edu\.{table} FOR ALL (.*?);", sql)
    assert policy, table
    body = policy.group(1)
    assert body.count("current_setting('edu.current_workspace_id', true)") == 2
    assert body.count("edu.can_read_workspace(workspace_id)") == 2


def test_tenant_tables_reference_workspaces(sql):
    for table in ("background_jobs", "usage_events", "workspace_quotas", "documents"):
        create = re.search(rf"CREATE TABLE edu\.{table} \((.*?)\);", sql).group(1)
        assert "workspace_id uuid" in create and "REFERENCES edu.workspaces(id)" in create


def test_runtime_grants_are_least_privilege(sql):
    grants = re.search(r"IF EXISTS \(SELECT FROM pg_roles WHERE rolname = 'eduvia_runtime'\)", sql)
    assert grants, "grants must be guarded by role existence"
    assert "REVOKE ALL ON edu.background_jobs, edu.usage_events, edu.workspace_quotas" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON edu.background_jobs, edu.documents" in sql
    assert "GRANT SELECT, INSERT ON edu.usage_events TO eduvia_runtime" in sql
    assert "GRANT SELECT, UPDATE (updated_at) ON edu.workspace_quotas" in sql
    assert not re.search(r"GRANT[^;]*DELETE[^;]*eduvia_runtime", sql)
    assert not re.search(r"GRANT[^;]*UPDATE[^;(]*ON edu\.usage_events", sql)


def test_definer_helpers_are_locked_down(sql):
    for function in ("job_actor", "overdue_job_ids", "provision_workspace_quota"):
        assert re.search(rf"FUNCTION edu\.{function}\([^)]*\)[^;]*SECURITY DEFINER", sql)
        assert re.search(
            rf"ALTER FUNCTION edu\.{function}\([^)]*\) OWNER TO eduvia_identity_owner", sql
        )
    assert sql.count("SET search_path=pg_catalog,edu") >= 3
    assert "FROM PUBLIC" in sql
    assert "REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner" in sql


def test_indexes_and_idempotency_constraint(sql):
    assert "UNIQUE (workspace_id, requested_by_user_id, idempotency_key)" in sql
    assert "background_jobs(workspace_id, status)" in sql
    assert "background_jobs(status, lease_expires_at)" in sql
    assert "background_jobs(workspace_id, created_at)" in sql
    assert (
        "FOREIGN KEY (workspace_id, job_id) REFERENCES edu.background_jobs(workspace_id, id)" in sql
    )
    assert "object_key = 'ws/' || workspace_id::text || '/doc/' || id::text" in sql
