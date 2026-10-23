"""Static checks of the 0016 privacy/consent migration SQL and model drift (no database)."""

import importlib.util
import re
from pathlib import Path

import pytest

from app.infrastructure.database import Base
from app.models import privacy  # noqa: F401

PATH = Path(__file__).parents[1] / "migrations" / "versions" / "0016_privacy_consent.py"
TENANT_TABLES = ("student_consents", "consent_links", "privacy_requests")
DEFINER_FUNCTIONS = (
    "student_set_birth_year",
    "student_consent_status",
    "consent_link_info",
    "guardian_consent_by_link",
    "erase_student",
    "erase_self",
    "student_export",
    "self_export",
)
INTERNAL_FUNCTIONS = (
    "privacy_min_age",
    "privacy_consent_required",
    "privacy_staff_role",
    "privacy_student_payload",
    "privacy_erase_student_row",
)


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("migration_0016", PATH)
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


def function_body(sql: str, name: str, args: str = "") -> str:
    match = re.search(rf"CREATE (?:OR REPLACE )?FUNCTION edu\.{name}\({args}(.*?)\$\$;", sql)
    assert match, name
    return match.group(1)


def runtime_block(sql: str) -> str:
    block = re.search(r"rolname = 'eduvia_runtime'\) THEN (.*?) END IF;", sql)
    assert block
    return block.group(1)


def test_revision_chain(migration):
    assert migration.revision == "0016_privacy_consent"
    assert migration.down_revision == "0015_assessment"
    with pytest.raises(RuntimeError):
        migration.downgrade()


def test_student_columns(sql):
    assert "ALTER TABLE edu.students ADD COLUMN birth_year smallint" in sql
    assert "CHECK (birth_year IS NULL OR birth_year BETWEEN 1900 AND 2100)" in sql
    assert (
        "ADD COLUMN consent_status text NOT NULL DEFAULT 'unknown' CHECK (consent_status IN "
        "('unknown','not_required','pending','granted','revoked'))" in sql
    )
    assert "ADD COLUMN erased_at timestamptz" in sql


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_new_tables_are_tenant_scoped_with_force_rls(sql, table):
    assert f"ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY" in sql
    assert f"ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY" in sql
    policy = re.search(rf"CREATE POLICY {table}_tenant ON edu\.{table} FOR ALL (.*?);", sql)
    assert policy, table
    assert policy.group(1).count("edu.can_read_workspace(workspace_id)") == 2
    body = create_body(sql, table)
    assert "workspace_id uuid NOT NULL REFERENCES edu.workspaces(id)" in body
    assert "FOREIGN KEY (workspace_id, student_id) REFERENCES edu.students(workspace_id, id)" in (
        body
    )


def test_consent_table_shape(sql):
    body = create_body(sql, "student_consents")
    assert "CHECK (method IN ('paper_school','guardian_link','self_adult'))" in body
    assert "policy_version text NOT NULL" in body
    assert "octet_length(guardian_contact_hash) = 32" in body  # digest only, no plaintext
    assert "guardian_contact " not in body and "guardian_email" not in body
    assert "length(evidence_note) <= 500" in body


def test_consent_links_are_digest_only_and_bounded(sql):
    body = create_body(sql, "consent_links")
    assert "CONSTRAINT uq_consent_links_token_hash UNIQUE (token_hash)" in body
    assert "octet_length(token_hash) = 32" in body
    assert "expires_at <= created_at + interval '30 days 1 hour'" in body
    assert " token text" not in body


def test_privacy_request_shape(sql):
    body = create_body(sql, "privacy_requests")
    assert "CHECK (kind IN ('export','erasure'))" in body
    assert "CHECK (status IN ('queued','succeeded','failed','rejected'))" in body
    assert "CHECK ((student_id IS NULL) <> (user_id IS NULL))" in body
    assert "'ws/' || workspace_id::text || '/privacy/' || id::text || '.json'" in body
    assert "'users/' || user_id::text || '/privacy/' || id::text || '.json'" in body


def test_guards(sql):
    assert "BEFORE INSERT OR UPDATE ON edu.student_consents" in sql
    assert "consent records are append-only" in sql
    assert "consent revocation is final" in sql
    assert "consent details can only be scrubbed" in sql
    assert "AFTER INSERT OR UPDATE OF revoked_at ON edu.student_consents" in sql
    assert "BEFORE UPDATE ON edu.privacy_requests" in sql
    assert "finished privacy request is final" in sql


def test_no_delete_grants_for_runtime(sql):
    block = runtime_block(sql)
    grants = re.findall(r"GRANT [^;]*? TO eduvia_runtime", block)
    assert not any("DELETE" in g.split(" ON ")[0] for g in grants)
    assert (
        "GRANT SELECT, INSERT, UPDATE ON edu.student_consents, edu.consent_links, "
        "edu.privacy_requests TO eduvia_runtime" in grants
    )
    assert re.search(r"REVOKE ALL ON edu\.student_consents, [^;]* FROM eduvia_runtime", block)
    execute = next(g for g in grants if g.startswith("GRANT EXECUTE"))
    for name in DEFINER_FUNCTIONS:
        assert f"edu.{name}(" in execute, name
    assert "edu.student_start_attempt(uuid, text, text, integer)" in execute
    for internal in INTERNAL_FUNCTIONS:
        assert internal not in execute, internal


@pytest.mark.parametrize("name", DEFINER_FUNCTIONS)
def test_definer_functions_are_narrow(sql, name):
    body = function_body(sql, name)
    assert "SECURITY DEFINER SET search_path=pg_catalog,edu" in body
    assert re.search(rf"ALTER FUNCTION edu\.{name}\([^)]*\) OWNER TO eduvia_identity_owner", sql)
    assert re.search(rf"REVOKE ALL ON FUNCTION [^;]*edu\.{name}\(", sql)
    assert "EXECUTE format" not in body and "EXECUTE '" not in body


@pytest.mark.parametrize("name", INTERNAL_FUNCTIONS)
def test_internal_helpers_are_not_definers(sql, name):
    body = function_body(sql, name)
    assert "SECURITY DEFINER" not in body
    assert re.search(rf"REVOKE ALL ON FUNCTION [^;]*edu\.{name}\(", sql)


@pytest.mark.parametrize(
    "name", ["student_set_birth_year", "student_consent_status", "erase_self", "self_export"]
)
def test_self_service_derives_the_actor(sql, name):
    body = function_body(sql, name)
    assert "edu.actor_id()" in body
    assert "current_workspace_id" not in body


@pytest.mark.parametrize("name", ["erase_student", "student_export"])
def test_staff_functions_require_workspace_context_and_staff_role(sql, name):
    assert "edu.privacy_staff_role(ws) IS NULL" in function_body(sql, name)
    role = function_body(sql, "privacy_staff_role")
    assert "current_setting('edu.current_workspace_id', true)" in role
    assert "m.role IN ('owner','admin','teacher')" in role


def test_exports_never_contain_keys_or_other_students(sql):
    for name in ("privacy_student_payload", "student_export", "self_export"):
        body = function_body(sql, name)
        assert "exam_answer_keys" not in body
        assert "correct_key" not in body and "explanation" not in body
        assert "guardian_contact_hash" not in body
    payload = function_body(sql, "privacy_student_payload")
    assert "g.released_at IS NOT NULL" in payload
    assert "q.student_id = s.id" in payload
    assert "WHERE s.user_id = actor" in function_body(sql, "self_export")


def test_erasure_pseudonymises_and_keeps_grades(sql):
    body = function_body(sql, "privacy_erase_student_row")
    assert "display_name = 'Học sinh đã xóa'" in body
    assert "external_code = NULL" in body and "user_id = NULL" in body
    assert "birth_year = NULL" in body and "erased_at = clock_timestamp()" in body
    assert "guardian_name = NULL, guardian_contact_hash = NULL" in body
    assert "DELETE" not in body  # attempts, answers and grades stay
    self_body = function_body(sql, "erase_self")
    assert "'erased+' || u.id::text || '@invalid'" in self_body
    assert "is_active = false" in self_body
    assert "SET status = 'revoked'" in self_body
    assert "edu.privacy_erase_student_row(r.id)" in self_body


def test_guardian_link_is_single_use_and_locked(sql):
    body = function_body(sql, "guardian_consent_by_link")
    assert "FOR UPDATE" in body
    assert "l.used_at IS NOT NULL OR l.expires_at <= clock_timestamp()" in body
    assert "ERRCODE = 'EV018'" in body
    assert "'guardian_link'" in body
    assert "SET used_at = clock_timestamp()" in body
    assert "edu.actor_id()" not in body  # no account needed
    info = function_body(sql, "consent_link_info")
    assert "regexp_replace(btrim(stu.display_name)" in info  # given name only


def test_start_attempt_consent_gate(sql):
    gated = function_body(
        sql,
        "student_start_attempt",
        r"p_assignment_id uuid, p_idempotency_key text, p_request_hash text, p_consent_age integer",
    )
    assert "ERRCODE = 'EV017'" in gated
    assert "edu.privacy_consent_required(stu_consent, stu_birth_year, p_consent_age)" in gated
    # Every 0015 rule is still there.
    for code in ("EV011", "EV012", "EV013", "P0002", "28000", "22023"):
        assert f"ERRCODE = '{code}'" in gated
    assert "pg_advisory_xact_lock(hashtext(" in gated
    assert "exam_answer_keys" not in gated and "correct_key" not in gated
    wrapper = re.search(
        r"CREATE OR REPLACE FUNCTION edu\.student_start_attempt\((.*?)\$\$;", sql
    ).group(1)
    assert "p_request_hash, 16)" in wrapper
    required = function_body(sql, "privacy_consent_required")
    assert "p_status IN ('unknown','pending','revoked')" in required
    assert "edu.privacy_min_age(p_birth_year) < p_consent_age" in required


def test_birth_year_rules(sql):
    body = function_body(sql, "student_set_birth_year")
    assert "ERRCODE = 'EV019'" in body
    assert "WHEN edu.privacy_min_age(p_year) >= p_consent_age THEN 'not_required'" in body
    assert "WHEN r.consent_status IN ('granted','revoked') THEN r.consent_status" in body
    assert "p_consent_age NOT BETWEEN 12 AND 18" in body
    assert "- p_birth_year - 1" in function_body(sql, "privacy_min_age")


def test_schema_create_is_balanced(sql):
    assert sql.count("GRANT CREATE ON SCHEMA edu TO eduvia_identity_owner") == sql.count(
        "REVOKE CREATE ON SCHEMA edu FROM eduvia_identity_owner"
    )


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_models_match_migration_columns(sql, table):
    model = Base.metadata.tables[f"edu.{table}"]
    body = create_body(sql, table)
    declared = re.findall(
        r"(?:^\s*|, )([a-z_0-9]+) "
        r"(?:uuid|text|integer|bigint|boolean|jsonb|bytea|timestamptz|numeric)",
        body,
    )
    assert sorted(declared) == sorted(c.name for c in model.columns), table
