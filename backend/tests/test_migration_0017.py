"""Static checks of the 0017 terms-acceptance / consent-mode migration SQL (no database)."""

import importlib.util
import re
from pathlib import Path

import pytest

VERSIONS = Path(__file__).parents[1] / "migrations" / "versions"
PATH = VERSIONS / "0017_terms_acceptance.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade_sql(module) -> str:
    statements = []

    class FakeOp:
        def execute(self, statement):
            statements.append(str(statement))

    original = module.op
    module.op = FakeOp()
    try:
        module.upgrade()
    finally:
        module.op = original
    return re.sub(r"\s+", " ", "\n".join(statements))


@pytest.fixture(scope="module")
def migration():
    return load(PATH, "migration_0017")


@pytest.fixture(scope="module")
def sql(migration):
    return upgrade_sql(migration)


def function_body(sql: str, name: str) -> str:
    match = re.search(rf"CREATE (?:OR REPLACE )?FUNCTION edu\.{name}\((.*?)\$\$;", sql)
    assert match, name
    return match.group(1)


def test_revision_chain(migration):
    assert migration.revision == "0017_terms_acceptance"
    assert migration.down_revision == "0016_privacy_consent"
    with pytest.raises(RuntimeError):
        migration.downgrade()


def test_agreement_table_shape(sql):
    body = re.search(r"CREATE TABLE edu\.user_agreements \((.*?)\); CREATE INDEX", sql).group(1)
    assert "user_id uuid NOT NULL REFERENCES edu.users(id)" in body
    assert "CHECK (document IN ('user_agreement','privacy_notice'))" in body
    assert "CHECK (method IN ('signup','reaccept'))" in body
    assert "octet_length(client_hash) = 32" in body
    assert "UNIQUE (user_id, document, version)" in body
    assert "workspace_id" not in body  # per user, not per tenant
    assert " ip " not in body and "ip_address" not in body and "inet" not in body


def test_agreements_are_self_scoped_with_force_rls(sql):
    assert "ALTER TABLE edu.user_agreements ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE edu.user_agreements FORCE ROW LEVEL SECURITY" in sql
    assert (
        "CREATE POLICY user_agreements_self_select ON edu.user_agreements FOR SELECT "
        "USING (user_id = edu.actor_id())" in sql
    )
    assert (
        "CREATE POLICY user_agreements_self_insert ON edu.user_agreements FOR INSERT "
        "WITH CHECK (user_id = edu.actor_id())" in sql
    )
    assert "current_workspace_id" not in re.search(r"CREATE POLICY user_agreements.*", sql)[0][:400]


def test_runtime_gets_select_insert_only(sql):
    block = re.search(r"rolname = 'eduvia_runtime'\) THEN (.*?) END IF;", sql).group(1)
    assert "REVOKE ALL ON edu.user_agreements FROM eduvia_runtime" in block
    assert "GRANT SELECT, INSERT ON edu.user_agreements TO eduvia_runtime" in block
    assert "UPDATE" not in block and "DELETE" not in block
    assert (
        "GRANT EXECUTE ON FUNCTION edu.record_agreements(text, text, text, bytea), "
        "edu.current_agreements() TO eduvia_runtime" in block
    )


@pytest.mark.parametrize("name", ["record_agreements", "current_agreements"])
def test_agreement_functions_are_narrow_definers(sql, name):
    body = function_body(sql, name)
    assert "SECURITY DEFINER SET search_path=pg_catalog,edu" in body
    assert "edu.actor_id()" in body
    assert "current_workspace_id" not in body
    assert re.search(rf"ALTER FUNCTION edu\.{name}\([^)]*\) OWNER TO eduvia_identity_owner", sql)
    assert re.search(rf"REVOKE ALL ON FUNCTION [^;]*edu\.{name}\(", sql)
    assert "EXECUTE format" not in body


def test_record_agreements_is_idempotent_and_counts(sql):
    body = function_body(sql, "record_agreements")
    assert "ON CONFLICT (user_id, document, version) DO NOTHING" in body
    assert "GET DIAGNOSTICS inserted = ROW_COUNT" in body
    assert "'user_agreement', p_user_agreement_version" in body
    assert "'privacy_notice', p_privacy_version" in body


def test_signup_sentinel_disables_the_gate(sql):
    helper = function_body(sql, "privacy_consent_required")
    assert "SELECT p_consent_age > 0 AND p_status IN" in helper
    start = function_body(sql, "student_start_attempt")
    assert "(p_consent_age > 0 AND p_consent_age NOT BETWEEN 12 AND 18)" in start
    assert "IF p_consent_age > 0 AND edu.privacy_consent_required(" in start
    assert "ERRCODE = 'EV017'" in start
    status = function_body(sql, "student_consent_status")
    assert "CASE WHEN p_consent_age <= 0 THEN 'not_required' ELSE s.consent_status END" in status
    birth = function_body(sql, "student_set_birth_year")
    assert "IF p_consent_age <= 0 THEN" in birth
    assert "out_consent_status := 'not_required'" in birth


def test_start_attempt_body_only_changes_the_gate():
    """0017 copies the 0016 body; everything except the consent-age handling is identical."""
    old = load(VERSIONS / "0016_privacy_consent.py", "migration_0016_copy").START_ATTEMPT_SQL
    new = load(PATH, "migration_0017_copy").START_ATTEMPT_SQL
    old = old.split("-- The 0015 signature stays callable")[0]

    def normalise(text: str) -> str:
        text = re.sub(r"--[^\n]*", "", text)
        text = re.sub(r"\s+", " ", text)
        text = text.replace("CREATE OR REPLACE FUNCTION", "CREATE FUNCTION")
        text = text.replace("(p_consent_age > 0 AND p_consent_age NOT BETWEEN 12 AND 18)", "X")
        text = text.replace("p_consent_age NOT BETWEEN 12 AND 18", "X")
        text = text.replace("p_consent_age > 0 AND edu.privacy_consent_required", "GATE")
        text = text.replace("edu.privacy_consent_required", "GATE")
        return re.sub(r"\s+", " ", text).strip()

    assert normalise(old) == normalise(new)
