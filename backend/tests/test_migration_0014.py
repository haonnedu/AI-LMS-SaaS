"""Static checks of the 0014 assessment migration SQL and model drift (no database)."""

import importlib.util
import re
from pathlib import Path

import pytest

from app.infrastructure.database import Base
from app.models import assessment  # noqa: F401

PATH = Path(__file__).parents[1] / "migrations" / "versions" / "0014_assessment.py"
TENANT_TABLES = (
    "assignments",
    "quiz_attempts",
    "student_answers",
    "grading_results",
    "grading_result_items",
    "grades",
)
STUDENT_FUNCTIONS = (
    "student_assignments",
    "student_assignment_detail",
    "student_attempt",
    "student_attempt_items",
    "student_start_attempt",
    "student_save_answer",
    "student_submit",
    "student_results",
)


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("migration_0011", PATH)
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


def function_body(sql: str, name: str) -> str:
    match = re.search(rf"CREATE FUNCTION edu\.{name}\((.*?)\$\$;", sql)
    assert match, name
    return match.group(1)


def runtime_grants(sql: str) -> list[str]:
    block = re.search(r"rolname = 'eduvia_runtime'\) THEN (.*?) END IF;", sql)
    assert block
    return re.findall(r"GRANT [^;]*? TO eduvia_runtime", block.group(1))


def test_revision_chain(migration):
    assert migration.revision == "0014_assessment"
    assert migration.down_revision == "0013_generation_exams"
    with pytest.raises(RuntimeError):
        migration.downgrade()


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_every_table_is_tenant_scoped_with_force_rls(sql, table):
    assert f"ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY" in sql
    assert f"ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY" in sql
    policy = re.search(rf"CREATE POLICY {table}_tenant ON edu\.{table} FOR ALL (.*?);", sql)
    assert policy, table
    assert policy.group(1).count("edu.can_read_workspace(workspace_id)") == 2
    assert "workspace_id uuid NOT NULL REFERENCES edu.workspaces(id)" in create_body(sql, table)


@pytest.mark.parametrize(
    "table,fk",
    [
        ("assignments", "FOREIGN KEY (workspace_id, class_id) REFERENCES edu.classes"),
        (
            "assignments",
            "FOREIGN KEY (workspace_id, exam_version_id) REFERENCES edu.exam_versions",
        ),
        (
            "quiz_attempts",
            "FOREIGN KEY (workspace_id, assignment_id, exam_version_id) "
            "REFERENCES edu.assignments(workspace_id, id, exam_version_id)",
        ),
        ("quiz_attempts", "FOREIGN KEY (workspace_id, student_id) REFERENCES edu.students"),
        (
            "student_answers",
            "FOREIGN KEY (workspace_id, attempt_id, exam_version_id) "
            "REFERENCES edu.quiz_attempts(workspace_id, id, exam_version_id)",
        ),
        (
            "student_answers",
            "FOREIGN KEY (workspace_id, exam_version_id, exam_item_id) "
            "REFERENCES edu.exam_items(workspace_id, exam_version_id, id)",
        ),
        (
            "grading_results",
            "FOREIGN KEY (workspace_id, attempt_id, supersedes_id) "
            "REFERENCES edu.grading_results(workspace_id, attempt_id, id)",
        ),
        (
            "grading_result_items",
            "FOREIGN KEY (workspace_id, exam_version_id, exam_item_id) "
            "REFERENCES edu.exam_items(workspace_id, exam_version_id, id)",
        ),
        (
            "grades",
            "FOREIGN KEY (workspace_id, attempt_id, grading_result_id) "
            "REFERENCES edu.grading_results(workspace_id, attempt_id, id)",
        ),
    ],
)
def test_composite_tenant_foreign_keys(sql, table, fk):
    assert fk in create_body(sql, table)


def test_attempt_and_grade_uniqueness(sql):
    attempts = create_body(sql, "quiz_attempts")
    assert "UNIQUE (assignment_id, student_id, attempt_no)" in attempts
    assert "UNIQUE (assignment_id, student_id, idempotency_key)" in attempts
    assert (
        "CREATE UNIQUE INDEX uq_quiz_attempts_in_progress ON "
        "edu.quiz_attempts(assignment_id, student_id) WHERE status = 'in_progress'" in sql
    )
    assert "UNIQUE (attempt_id, exam_item_id)" in create_body(sql, "student_answers")
    assert "UNIQUE (attempt_id, run_key)" in create_body(sql, "grading_results")
    assert "UNIQUE (attempt_id, revision_no)" in create_body(sql, "grades")
    assert "CREATE UNIQUE INDEX uq_grades_current ON edu.grades(attempt_id) WHERE is_current" in sql
    assert "max_attempts integer NOT NULL DEFAULT 1 CHECK (max_attempts BETWEEN 1 AND 5)" in sql


def test_release_policies_and_bounds(sql):
    body = create_body(sql, "assignments")
    assert "CHECK (score_release IN ('immediate','after_close','manual'))" in body
    assert "CHECK (solution_release IN ('never','after_close','manual'))" in body
    assert "score_release <> 'after_close' AND solution_release <> 'after_close'" in body
    assert "CHECK (closes_at IS NULL OR closes_at > opens_at)" in body
    grades = create_body(sql, "grades")
    assert "score >= 0 AND score <= max_score" in grades
    assert "approved_by_user_id IS NOT NULL AND reason IS NOT NULL" in grades


def test_guards(sql):
    assert "BEFORE INSERT OR UPDATE ON edu.assignments" in sql
    assert "published assignment pin is immutable" in sql
    assert "published closing time may only be extended" in sql
    assert "archived assignment is immutable" in sql
    assert "release stamps are immutable" in sql
    assert "BEFORE UPDATE ON edu.quiz_attempts" in sql
    assert "submitted attempt is frozen" in sql
    assert "BEFORE INSERT OR UPDATE ON edu.student_answers" in sql
    assert "answers are frozen once the attempt leaves in_progress" in sql
    assert "BEFORE INSERT OR UPDATE ON edu.grades" in sql
    assert "grade revisions are append-only" in sql
    assert "grade release cannot be recalled" in sql


def test_least_privilege_runtime_grants(sql):
    grants = runtime_grants(sql)
    assert not any("DELETE" in g.split(" ON ")[0] for g in grants)
    assert (
        "GRANT SELECT, INSERT ON edu.grading_results, edu.grading_result_items TO eduvia_runtime"
        in grants
    )
    assert not any("grading_result" in g and "UPDATE" in g for g in grants)
    assert re.search(r"REVOKE ALL ON [^;]*edu\.grades FROM eduvia_runtime", sql)
    execute = next(g for g in grants if g.startswith("GRANT EXECUTE"))
    for name in (*STUDENT_FUNCTIONS, "expire_attempts", "apply_due_releases"):
        assert f"edu.{name}(" in execute, name
    for internal in ("finalize_attempt", "attempt_snapshot_sha256", "assessment_actor_student"):
        assert internal not in execute, internal


@pytest.mark.parametrize("name", [*STUDENT_FUNCTIONS, "expire_attempts", "apply_due_releases"])
def test_definer_functions_are_narrow(sql, name):
    body = function_body(sql, name)
    assert "SECURITY DEFINER SET search_path=pg_catalog,edu" in body
    assert re.search(rf"ALTER FUNCTION edu\.{name}\([^)]*\) OWNER TO eduvia_identity_owner", sql)
    assert re.search(rf"REVOKE ALL ON FUNCTION [^;]*edu\.{name}\(", sql)
    assert "EXECUTE format" not in body and "EXECUTE '" not in body  # no dynamic SQL


@pytest.mark.parametrize("name", STUDENT_FUNCTIONS)
def test_student_functions_derive_the_student_from_verified_identity(sql, name):
    body = function_body(sql, name)
    assert "edu.actor_id()" in body or "edu.assessment_actor_student(" in body
    assert "current_workspace_id" not in body  # never trusts a caller-chosen workspace


@pytest.mark.parametrize(
    "name",
    [
        "student_assignments",
        "student_assignment_detail",
        "student_attempt",
        "student_attempt_items",
        "student_start_attempt",
        "student_save_answer",
        "student_submit",
    ],
)
def test_keys_never_leave_through_pre_release_functions(sql, name):
    body = function_body(sql, name)
    assert "exam_answer_keys" not in body
    assert "correct_key" not in body and "explanation" not in body
    assert "exam_keys_for_scoring" not in body


def test_results_gate_keys_on_solution_release(sql):
    body = function_body(sql, "student_results")
    assert "solutions := asg.solutions_released_at IS NOT NULL" in body
    keyed, unkeyed = body.split("ELSIF att.status IN ('submitted','graded') THEN")
    assert "IF att.status IN ('submitted','graded') AND solutions THEN" in keyed
    assert "exam_answer_keys" in keyed and "exam_answer_keys" not in unkeyed
    assert "gr.released_at IS NOT NULL" in body
    assert "'score', CASE WHEN released THEN g.score::text END" in body


def test_attempt_items_rebuild_choices_without_extra_fields(sql):
    body = function_body(sql, "student_attempt_items")
    assert "jsonb_build_object('key', c.value->>'key', 'text', c.value->>'text')" in body


def test_start_serializes_and_enforces_policy(sql):
    body = function_body(sql, "student_start_attempt")
    assert "pg_advisory_xact_lock(hashtext(" in body
    assert "now_ts := clock_timestamp()" in body
    assert "ERRCODE = 'EV011'" in body and "ERRCODE = 'EV012'" in body
    assert "ERRCODE = 'EV013'" in body
    assert "LEAST(asg.closes_at," in body
    # The existing in-progress attempt is returned regardless of the new key.
    assert "q.status = 'in_progress'" in body


def test_writes_lock_the_attempt_and_check_fresh_deadline(sql):
    for name in ("student_save_answer", "student_submit"):
        body = function_body(sql, name)
        assert "FOR UPDATE" in body
        assert "now_ts := clock_timestamp()" in body
        assert "interval '5 seconds'" in body
    save = function_body(sql, "student_save_answer")
    assert "ERRCODE = 'EV010'" in save and "ERRCODE = 'EV014'" in save
    assert "ERRCODE = 'EV015'" in save and "ERRCODE = 'EV016'" in save
    assert "p_client_sequence <= ans.client_sequence" in save


def test_single_finalization_path(sql):
    for name in ("student_submit", "expire_attempts"):
        assert "edu.finalize_attempt(" in function_body(sql, name)
    finalize = function_body(sql, "finalize_attempt")
    assert "SECURITY DEFINER" not in finalize  # internal; executes only inside definers
    assert "att.status <> 'in_progress' THEN RETURN NULL" in finalize
    assert "edu.attempt_snapshot_sha256(att.id)" in finalize
    assert "'system:attempt.grade:' || att.id::text" in finalize
    assert "ON CONFLICT ON CONSTRAINT uq_background_jobs_idempotency DO NOTHING" in finalize
    assert "FOR UPDATE SKIP LOCKED" in function_body(sql, "expire_attempts")
    assert "LEAST(coalesce(p_now, clock_timestamp()), clock_timestamp())" in function_body(
        sql, "expire_attempts"
    )
    assert "WITH CHECK (kind = 'attempt.grade')" in sql


def test_snapshot_function_matches_python_canonical_form(sql):
    body = function_body(sql, "attempt_snapshot_sha256")
    assert "a.exam_item_id::text || ':' || coalesce(a.response->>'selectedKey', '')" in body
    assert "chr(10) ORDER BY a.exam_item_id" in body


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
