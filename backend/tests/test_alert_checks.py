"""Threshold logic of deploy/alerts/check.py (PILOT-04), with a fake cursor; no database."""

import importlib.util
import re
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECK_PATH = ROOT / "deploy" / "alerts" / "check.py"
QUERIES_PATH = ROOT / "deploy" / "alerts" / "queries.sql"
EXPECTED = {
    "queue_lag_seconds": Decimal(300),
    "failed_jobs_last_hour": Decimal(0),
    "quota_exhausted_workspaces": Decimal(0),
    "attempts_in_progress_past_deadline": Decimal(0),
    "grading_pending_over_10_minutes": Decimal(0),
}


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("eduvia_alert_check", CHECK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checks(check):
    return check.parse_queries(QUERIES_PATH.read_text(encoding="utf-8"))


class FakeCursor:
    """Answers the role probe and each named check with a configured value."""

    def __init__(self, values, *, bypass=True, fail=()):
        self.values = values
        self.bypass = bypass
        self.fail = set(fail)
        self.executed: list[str] = []
        self._row = None

    def execute(self, sql):
        self.executed.append(sql)
        if "pg_roles" in sql:
            self._row = (self.bypass,)
            return
        if sql.startswith("SET "):
            self._row = None
            return
        for name, value in self.values.items():
            if name in self.fail and self._matches(name, sql):
                raise RuntimeError("boom")
            if self._matches(name, sql):
                self._row = None if value is ... else (value,)
                return
        raise AssertionError(f"unexpected SQL: {sql[:60]}")

    def _matches(self, name, sql):
        return self.sql_for[name] == sql

    def fetchone(self):
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.read_only = False

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def cursor_for(checks, values, **kwargs):
    cursor = FakeCursor(values, **kwargs)
    cursor.sql_for = {c.name: c.sql for c in checks}
    return cursor


def test_queries_file_defines_the_named_checks(checks):
    assert {c.name: c.threshold for c in checks} == EXPECTED
    for c in checks:
        assert c.sql.lstrip().upper().startswith("SELECT"), c.name
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT)\b", c.sql.upper())
        # Aggregates only: no identifiers leave the database through alerts.
        assert re.search(r"\b(count|max)\(", c.sql), c.name


def test_threshold_is_strictly_greater(check, checks):
    lag = next(c for c in checks if c.name == "queue_lag_seconds")
    assert not check.evaluate(lag, 300).breached
    assert check.evaluate(lag, 301).breached
    assert not check.evaluate(lag, None).breached  # empty queue => 0
    failed = next(c for c in checks if c.name == "failed_jobs_last_hour")
    assert not check.evaluate(failed, 0).breached
    assert check.evaluate(failed, 1).breached
    assert check.evaluate(failed, Decimal("0.5")).breached


def test_environment_override(check, checks):
    lag = next(c for c in checks if c.name == "queue_lag_seconds")
    env = {"ALERT_THRESHOLD_QUEUE_LAG_SECONDS": "900"}
    assert check.effective_threshold(lag, env) == Decimal(900)
    assert check.effective_threshold(lag, {}) == Decimal(300)
    with pytest.raises(ValueError):
        check.effective_threshold(lag, {"ALERT_THRESHOLD_QUEUE_LAG_SECONDS": "soon"})


def test_parse_rejects_incomplete_checks(check):
    with pytest.raises(ValueError):
        check.parse_queries("-- name: a\nSELECT 1;\n")  # no threshold
    with pytest.raises(ValueError):
        check.parse_queries("-- name: a\n-- threshold: > 1\n")  # no statement
    with pytest.raises(ValueError):
        check.parse_queries("-- name: a\n-- threshold: > 1\nSELECT 1; SELECT 2;\n")
    with pytest.raises(ValueError):
        check.parse_queries(
            "-- name: a\n-- threshold: > 1\nSELECT 1;\n-- name: a\n-- threshold: > 1\nSELECT 2;"
        )
    with pytest.raises(ValueError):
        check.parse_queries("-- just a comment\n")


def test_all_green_exits_zero(check, checks, capsys):
    values = {name: 0 for name in EXPECTED} | {"queue_lag_seconds": 12}
    cursor = cursor_for(checks, values)
    code = check.main(
        [],
        {"DATABASE_URL": "postgresql+psycopg://u:p@h/db"},
        lambda *a, **k: FakeConnection(cursor),
    )
    out = capsys.readouterr()
    assert code == 0
    assert out.out.count("OK") == 5
    assert "u:p@h" not in out.out + out.err
    assert cursor.executed[0].startswith("SET statement_timeout")


def test_breach_exits_one_and_names_the_check(check, checks, capsys):
    values = {name: 0 for name in EXPECTED} | {"grading_pending_over_10_minutes": 3}
    cursor = cursor_for(checks, values)
    code = check.main(
        [], {"DATABASE_URL": "postgresql://x"}, lambda *a, **k: FakeConnection(cursor)
    )
    assert code == 1
    assert "BREACH grading_pending_over_10_minutes=3" in capsys.readouterr().out


def test_override_can_silence_a_known_breach(check, checks):
    values = {name: 0 for name in EXPECTED} | {"queue_lag_seconds": 600}
    cursor = cursor_for(checks, values)
    env = {"DATABASE_URL": "postgresql://x", "ALERT_THRESHOLD_QUEUE_LAG_SECONDS": "900"}
    assert check.main([], env, lambda *a, **k: FakeConnection(cursor)) == 0


def test_query_error_or_missing_row_exits_two(check, checks):
    values = {name: 0 for name in EXPECTED}
    cursor = cursor_for(checks, values, fail={"failed_jobs_last_hour"})
    assert (
        check.main([], {"DATABASE_URL": "postgresql://x"}, lambda *a, **k: FakeConnection(cursor))
        == 2
    )
    cursor = cursor_for(checks, values | {"queue_lag_seconds": ...})
    assert (
        check.main([], {"DATABASE_URL": "postgresql://x"}, lambda *a, **k: FakeConnection(cursor))
        == 2
    )


def test_refuses_a_role_that_cannot_bypass_rls(check, checks, capsys):
    cursor = cursor_for(checks, {name: 0 for name in EXPECTED}, bypass=False)
    code = check.main(
        [], {"DATABASE_URL": "postgresql://x"}, lambda *a, **k: FakeConnection(cursor)
    )
    assert code == 2
    assert "row level security" in capsys.readouterr().err
    assert len(cursor.executed) == 2  # timeout + role probe; no check ran


def test_missing_url_and_connection_failure_exit_two(check, capsys):
    assert check.main([], {}, None) == 2

    def broken(*args, **kwargs):
        raise OSError("could not connect to postgresql://u:secret@h/db")

    assert check.main([], {"DATABASE_URL": "postgresql://u:secret@h/db"}, broken) == 2
    assert "secret" not in capsys.readouterr().err


def test_only_selects_named_checks(check, checks, capsys):
    cursor = cursor_for(checks, {"queue_lag_seconds": 1})
    code = check.main(
        ["--only", "queue_lag_seconds"],
        {"DATABASE_URL": "postgresql://x"},
        lambda *a, **k: FakeConnection(cursor),
    )
    assert code == 0
    assert check.main(["--only", "nope"], {"DATABASE_URL": "postgresql://x"}, None) == 2


def test_libpq_url_strips_the_sqlalchemy_driver(check):
    assert check.libpq_url("postgresql+psycopg://a@b/c") == "postgresql://a@b/c"
    assert check.libpq_url("postgresql://a@b/c") == "postgresql://a@b/c"
