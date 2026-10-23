"""M4/M5/M6-QA static release gates (no database, no network).

These gates run on every ``pytest`` invocation and guard invariants that are cheap to check
statically but expensive to lose:

(a) answer-key leak scan over the generated OpenAPI schema of the live FastAPI app;
(b) every workspace-scoped operation documents 401 and 404 (non-member => 404, never 403);
(c) FORCE ROW LEVEL SECURITY on every table created by migrations 0008-0014 and no runtime
    DELETE (direct grant or surviving default privilege) on append-only/secret tables;
(d) forward-only policy: every migration after 0009 has a ``downgrade`` that only raises
(Duc's identity migrations 0005-0007 are forward-only as well);
(e) exactly one Alembic head.

They complement, not replace, the PostgreSQL integration suites gated on
``AUTH_TEST_DATABASE_URL`` (RLS behaviour can only be proven against a real database).
When the tree violates a gate, the failing case is marked ``xfail`` with the reason instead of
relaxing the rule; see ``KNOWN_VIOLATIONS``.
"""

import ast
import importlib.util
import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.main import app
from app.services import question_bank

BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "migrations" / "versions"

# Property names that must never be reachable from a student-facing response schema.
FORBIDDEN_NAMES = frozenset(
    {
        "key",
        "keys",
        "correctkey",
        "correctkeys",
        "answerkey",
        "answerkeys",
        "explanation",
        "explanations",
        "rationale",
        "rationales",
        "solution",
        "solutions",
    }
)
FORBIDDEN_FRAGMENTS = ("correctkey", "answerkey", "explanation", "rationale")

# The single documented exception: the results DTO carries a nullable ``solution`` object that
# the database fills only after the teacher's solution release (edu.student_results).
RESULTS_ITEM_SCHEMA = "app__api__student__ResultItemDTO"
RELEASED_SOLUTION_SCHEMA = "ReleasedSolutionDTO"
# A multiple-choice option label (``{"key": "A", "text": "..."}``) is not an answer key. It is
# accepted only on a schema whose property set is exactly {key, text}; adding any other field to
# that schema re-arms the gate.
CHOICE_LABEL_SHAPE = frozenset({"key", "text"})

PROTECTED_TABLES = (
    "question_keys",
    "exam_answer_keys",
    "document_chunks",
    "usage_events",
    "grading_results",
)

# Gate id -> reason. Empty means the current tree satisfies every gate.
KNOWN_VIOLATIONS: dict[str, str] = {}


def known(case: str) -> None:
    if case in KNOWN_VIOLATIONS:
        pytest.xfail(KNOWN_VIOLATIONS[case])


# ---- OpenAPI helpers --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def openapi() -> dict:
    return app.openapi()


def _ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _forbidden(name: str) -> bool:
    flat = name.replace("_", "").replace("-", "").lower()
    return flat in FORBIDDEN_NAMES or any(fragment in flat for fragment in FORBIDDEN_FRAGMENTS)


def _nullable_ref(schema: dict, target: str) -> bool:
    options = schema.get("anyOf") or schema.get("oneOf") or []
    refs = {_ref_name(o["$ref"]) for o in options if "$ref" in o}
    return refs == {target} and any(o.get("type") == "null" for o in options)


def scan(schema: dict, components: dict, where: str, seen: set[str]) -> list[str]:
    """Return ``where.path.property`` for every forbidden property reachable from ``schema``."""
    hits: list[str] = []
    if not isinstance(schema, dict):
        return hits
    if "$ref" in schema:
        name = _ref_name(schema["$ref"])
        if name in seen:
            return hits
        seen.add(name)
        return scan(components[name], components, name, seen)
    properties = schema.get("properties", {})
    for prop, sub in properties.items():
        if _forbidden(prop):
            if where == RESULTS_ITEM_SCHEMA and prop == "solution":
                if not _nullable_ref(sub, RELEASED_SOLUTION_SCHEMA):
                    hits.append(
                        f"{where}.solution (must stay a nullable {RELEASED_SOLUTION_SCHEMA})"
                    )
                continue  # documented post-release payload; do not descend
            if prop == "key" and frozenset(properties) == CHOICE_LABEL_SHAPE:
                continue  # option label, not an answer key
            hits.append(f"{where}.{prop}")
        hits.extend(scan(sub, components, f"{where}.{prop}", seen))
    for keyword in ("items", "additionalProperties", "not"):
        if isinstance(schema.get(keyword), dict):
            hits.extend(scan(schema[keyword], components, f"{where}[]", seen))
    for keyword in ("anyOf", "oneOf", "allOf", "prefixItems"):
        for option in schema.get(keyword, []) or []:
            hits.extend(scan(option, components, where, seen))
    return hits


def response_schemas(operation: dict) -> list[tuple[str, dict]]:
    out = []
    for status, response in operation.get("responses", {}).items():
        for media in response.get("content", {}).values():
            out.append((status, media.get("schema", {})))
    return out


def student_roots(openapi: dict) -> list[tuple[str, dict]]:
    roots: list[tuple[str, dict]] = []
    for path, operations in openapi["paths"].items():
        student = path.startswith("/v1/student/") or path.endswith("/student-view")
        for method, operation in operations.items():
            if student:
                for status, schema in response_schemas(operation):
                    roots.append((f"{method.upper()} {path} -> {status}", schema))
    for name in openapi["components"]["schemas"]:
        if name.startswith("Student"):
            roots.append((f"component {name}", {"$ref": f"#/components/schemas/{name}"}))
    return roots


# ---- (a) key-leak scan ------------------------------------------------------------------------


def test_scan_covers_the_student_surface(openapi):
    roots = [label for label, _ in student_roots(openapi)]
    assert any(label.startswith("GET /v1/student/attempts/{attempt_id}/results") for label in roots)
    assert any("/student-view" in label for label in roots)
    assert any(label == "component StudentExamItemDTO" for label in roots)
    assert len([r for r in roots if r.startswith(("GET /v1/student", "POST /v1/student"))]) >= 8


def test_scanner_detects_a_planted_key():
    components = {
        "Leaky": {"properties": {"items": {"type": "array", "items": {"$ref": "#/x/Item"}}}},
        "Item": {"properties": {"stem": {}, "correctKey": {}, "choices": {"$ref": "#/x/C"}}},
        "C": {"properties": {"key": {}, "text": {}, "isCorrect": {}}},
    }
    hits = scan({"$ref": "#/x/Leaky"}, components, "root", set())
    assert "Item.correctKey" in hits
    assert "C.key" in hits  # a choice with extra fields is no longer a bare option label


def test_no_answer_key_reachable_from_student_responses(openapi):
    known("a-openapi")
    components = openapi["components"]["schemas"]
    leaks = {}
    for label, schema in student_roots(openapi):
        hits = scan(schema, components, label, set())
        if hits:
            leaks[label] = hits
    assert not leaks, leaks


def test_results_solution_is_the_only_exception_and_stays_nullable(openapi):
    components = openapi["components"]["schemas"]
    item = components[RESULTS_ITEM_SCHEMA]["properties"]
    assert _nullable_ref(item["solution"], RELEASED_SOLUTION_SCHEMA)
    assert set(components[RELEASED_SOLUTION_SCHEMA]["properties"]) == {"correctKey", "explanation"}
    results = openapi["paths"]["/v1/student/attempts/{attempt_id}/results"]["get"]
    assert response_schemas(results)[0][1] == {"$ref": "#/components/schemas/StudentResultDTO"}


def test_student_question_export_has_no_key_columns(openapi):
    """``questions/export?audience=student`` is documented as an untyped CSV body, so the OpenAPI
    walk cannot see its columns: pin the student column set and the rendered output instead."""
    known("a-export")
    export = openapi["paths"]["/v1/workspaces/{workspace_id}/questions/export"]["get"]
    audience = next(p for p in export["parameters"] if p["name"] == "audience")
    assert set(audience["schema"]["enum"]) == {"teacher", "student"}
    leaked = [c for c in question_bank.STUDENT_EXPORT_COLUMNS if _forbidden(c)]
    assert not leaked, leaked
    row = question_bank.TeacherExportRow(
        id="00000000-0000-0000-0000-000000000001",
        stem="Stem",
        choices=[{"key": k, "text": f"opt {k}"} for k in "ABCD"],
        difficulty=1,
        cognitive_level="remember",
        unit_code="T10-01",
        correct_key="C",
        explanation="SECRET-EXPLANATION",
    )
    rendered = question_bank.student_csv([row])
    header = rendered.lstrip("\ufeff").splitlines()[0].lower()
    assert "SECRET-EXPLANATION" not in rendered
    assert not any(fragment in header.replace("_", "") for fragment in FORBIDDEN_FRAGMENTS)


# ---- (b) workspace routes document 401 + 404 ---------------------------------------------------


def test_every_workspace_operation_declares_401_and_404(openapi):
    known("b")
    prefix = "/v1/workspaces/{workspace_id}"
    missing = []
    checked = 0
    for path, operations in openapi["paths"].items():
        if path != prefix and not path.startswith(prefix + "/"):
            continue
        for method, operation in operations.items():
            checked += 1
            absent = {"401", "404"} - set(operation.get("responses", {}))
            if absent:
                missing.append(f"{method.upper()} {path}: {sorted(absent)}")
    assert checked >= 60
    assert not missing, missing


# ---- migration helpers ------------------------------------------------------------------------


def migration_files() -> list[Path]:
    return sorted(VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py"))


def number(path: Path) -> int:
    return int(path.name[:4])


def load(path: Path):
    spec = importlib.util.spec_from_file_location(f"qa_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rendered_upgrade(path: Path) -> str:
    statements: list[str] = []

    class FakeOp:
        def execute(self, statement):
            statements.append(str(statement))

    module = load(path)
    module.op = FakeOp()
    module.upgrade()
    return re.sub(r"\s+", " ", "\n".join(statements))


@pytest.fixture(scope="module")
def tenant_sql() -> dict[str, str]:
    return {p.name: rendered_upgrade(p) for p in migration_files() if 9 <= number(p) <= 15}


def created_tables(sql: str) -> dict[str, str]:
    return {
        m.group(1): m.group(2)
        for m in re.finditer(r"CREATE TABLE edu\.(\w+) \((.*?)\);", sql, flags=re.S)
    }


def runtime_table_grants(sql: str) -> list[tuple[str, list[str]]]:
    grants = []
    for m in re.finditer(r"GRANT ([^;]*?) ON ([^;]*?) TO eduvia_runtime", sql):
        privileges, target = m.group(1).upper(), m.group(2)
        if target.lstrip().upper().startswith(("FUNCTION", "ALL ", "SCHEMA", "SEQUENCE")):
            continue
        tables = [t.strip().removeprefix("edu.") for t in target.split(",")]
        grants.append((privileges, tables))
    return grants


# ---- (c) FORCE RLS and no runtime DELETE on protected tables -----------------------------------


def test_every_table_from_0008_to_0014_forces_rls(tenant_sql):
    known("c-force")
    combined = " ".join(tenant_sql.values())
    tables = {}
    for name, sql in tenant_sql.items():
        tables.update({table: name for table in created_tables(sql)})
    assert len(tables) >= 37, sorted(tables)
    missing = [
        f"{table} ({name})"
        for table, name in sorted(tables.items())
        if f"ALTER TABLE edu.{table} FORCE ROW LEVEL SECURITY" not in combined
        or f"ALTER TABLE edu.{table} ENABLE ROW LEVEL SECURITY" not in combined
    ]
    assert not missing, missing


def test_tenant_tables_carry_a_workspace_id(tenant_sql):
    catalog = {"curriculum_subjects", "curriculum_units"}
    without = [
        table
        for sql in tenant_sql.values()
        for table, body in created_tables(sql).items()
        if table not in catalog
        and not re.search(r"\bworkspace_id uuid (NOT NULL|PRIMARY KEY)", body)
    ]
    assert not without, without


def test_runtime_has_no_delete_grant_on_protected_tables(tenant_sql):
    known("c-delete")
    offending = [
        f"{name}: GRANT {privileges} ON {', '.join(tables)}"
        for name, sql in tenant_sql.items()
        for privileges, tables in runtime_table_grants(sql)
        if ("DELETE" in privileges or "ALL" in privileges.split())
        and set(tables) & set(PROTECTED_TABLES)
    ]
    assert not offending, offending


def test_default_delete_privilege_is_revoked_on_protected_tables(tenant_sql):
    """deploy/postgres/bootstrap.sql grants SELECT/INSERT/UPDATE/DELETE on every migrator-created
    table by default, so each protected table must be explicitly REVOKEd from the runtime role."""
    bootstrap = (BACKEND.parent / "deploy" / "postgres" / "bootstrap.sql").read_text("utf-8")
    assert re.search(r"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO eduvia_runtime", bootstrap)
    revoked = set()
    for sql in tenant_sql.values():
        for m in re.finditer(r"REVOKE ALL ON ([^;]*?) FROM eduvia_runtime", sql):
            revoked.update(t.strip().removeprefix("edu.") for t in m.group(1).split(","))
    missing = [t for t in PROTECTED_TABLES if t not in revoked]
    assert not missing, missing


# ---- (d) forward-only migrations ---------------------------------------------------------------


def _downgrade_only_raises(source: str) -> bool:
    tree = ast.parse(source)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "downgrade"]
    if len(functions) != 1:
        return False
    body = functions[0].body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]  # docstring
    return len(body) == 1 and isinstance(body[0], ast.Raise)


@pytest.mark.parametrize(
    "path", [p for p in migration_files() if number(p) > 9], ids=lambda p: p.stem
)
def test_migrations_after_0008_are_forward_only(path):
    known(f"d-{path.stem}")
    assert _downgrade_only_raises(path.read_text("utf-8")), f"{path.name} must only raise"


def test_forward_only_check_rejects_a_destructive_downgrade():
    bad = 'def downgrade():\n    op.execute("DROP TABLE edu.x")\n'
    good = 'def downgrade():\n    """No."""\n    raise RuntimeError("forward-only")\n'
    two = 'def downgrade():\n    print("x")\n    raise RuntimeError("forward-only")\n'
    assert not _downgrade_only_raises(bad)
    assert not _downgrade_only_raises(two)
    assert not _downgrade_only_raises("def upgrade():\n    pass\n")
    assert _downgrade_only_raises(good)


# ---- (e) single Alembic head -------------------------------------------------------------------


def test_alembic_has_exactly_one_head():
    known("e")
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    assert len(script.get_bases()) == 1
    revisions = list(script.walk_revisions())
    assert len(revisions) == len(migration_files())
