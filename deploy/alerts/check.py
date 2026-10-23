#!/usr/bin/env python3
"""Run the named alert checks in deploy/alerts/queries.sql against DATABASE_URL.

Usage:
    DATABASE_URL=postgresql://... python3 deploy/alerts/check.py [--queries PATH] [--only NAME]

Exit codes: 0 all checks within threshold, 1 at least one breach, 2 configuration/connection
error or a role that cannot see tenant rows (results would be falsely green).

Prints one line per check and never prints the connection URL or credentials. Requires only
the standard library plus psycopg (already a backend dependency). Thresholds come from the
"-- threshold: > N" header of each check and can be overridden with
ALERT_THRESHOLD_<NAME_UPPERCASE>=N.
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

DEFAULT_QUERIES = Path(__file__).with_name("queries.sql")
STATEMENT_TIMEOUT_MS = 10_000
_NAME = re.compile(r"^--\s*name:\s*([a-z][a-z0-9_]*)\s*$")
_THRESHOLD = re.compile(r"^--\s*threshold:\s*>\s*(-?\d+(?:\.\d+)?)\s*$")

OK, BREACH, ERROR = 0, 1, 2


@dataclass(frozen=True)
class Check:
    name: str
    threshold: Decimal
    sql: str


@dataclass(frozen=True)
class Outcome:
    name: str
    value: Decimal | None
    threshold: Decimal
    breached: bool
    error: str | None = None

    def line(self) -> str:
        if self.error:
            return f"ERROR  {self.name}: {self.error}"
        state = "BREACH" if self.breached else "OK    "
        return f"{state} {self.name}={self.value} (threshold > {self.threshold})"


def parse_queries(text: str) -> list[Check]:
    """Split queries.sql into named checks; every check needs a name, threshold and statement."""
    checks: list[Check] = []
    name: str | None = None
    threshold: Decimal | None = None
    body: list[str] = []

    def flush() -> None:
        if name is None:
            return
        sql = "\n".join(body).strip().rstrip(";").strip()
        if threshold is None or not sql:
            raise ValueError(f"check {name!r} needs a '-- threshold: > N' line and a statement")
        if ";" in sql:
            raise ValueError(f"check {name!r} must contain exactly one statement")
        checks.append(Check(name, threshold, sql))

    for raw in text.splitlines():
        line = raw.strip()
        if match := _NAME.match(line):
            flush()
            name, threshold, body = match.group(1), None, []
        elif name is not None and (match := _THRESHOLD.match(line)):
            threshold = Decimal(match.group(1))
        elif name is not None and line and not line.startswith("--"):
            body.append(raw)
    flush()
    names = [c.name for c in checks]
    if len(set(names)) != len(names):
        raise ValueError("duplicate check names")
    if not checks:
        raise ValueError("no checks found")
    return checks


def effective_threshold(check: Check, environ: dict[str, str]) -> Decimal:
    override = environ.get(f"ALERT_THRESHOLD_{check.name.upper()}")
    if override is None:
        return check.threshold
    try:
        return Decimal(override)
    except InvalidOperation as exc:
        raise ValueError(f"invalid threshold override for {check.name}") from exc


def to_number(value: Any) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, bool):
        return Decimal(int(value))
    return Decimal(str(value))


def evaluate(check: Check, value: Any, threshold: Decimal | None = None) -> Outcome:
    limit = check.threshold if threshold is None else threshold
    number = to_number(value)
    return Outcome(check.name, number, limit, number > limit)


def can_see_tenant_rows(cursor) -> bool:
    cursor.execute(
        "SELECT rolsuper OR rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = current_user"
    )
    row = cursor.fetchone()
    return bool(row and row[0])


def run_checks(cursor, checks: list[Check], environ: dict[str, str]) -> list[Outcome]:
    outcomes = []
    for check in checks:
        threshold = effective_threshold(check, environ)
        try:
            cursor.execute(check.sql)
            row = cursor.fetchone()
        except Exception as exc:  # report and keep going; the run still exits non-zero
            outcomes.append(Outcome(check.name, None, threshold, True, type(exc).__name__))
            continue
        if row is None:
            outcomes.append(Outcome(check.name, None, threshold, True, "no row returned"))
            continue
        outcomes.append(evaluate(check, row[0], threshold))
    return outcomes


def exit_code(outcomes: list[Outcome]) -> int:
    if any(o.error for o in outcomes):
        return ERROR
    return BREACH if any(o.breached for o in outcomes) else OK


def libpq_url(url: str) -> str:
    """Accept SQLAlchemy-style URLs (postgresql+psycopg://) used by the backend settings."""
    return re.sub(r"^postgresql\+\w+://", "postgresql://", url)


def main(argv: list[str] | None = None, environ: dict[str, str] | None = None, connect=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--only", action="append", default=[], help="run only this check")
    args = parser.parse_args(argv)
    environ = dict(os.environ if environ is None else environ)
    try:
        checks = parse_queries(args.queries.read_text(encoding="utf-8"))
        if args.only:
            unknown = set(args.only) - {c.name for c in checks}
            if unknown:
                raise ValueError(f"unknown check(s): {', '.join(sorted(unknown))}")
            checks = [c for c in checks if c.name in args.only]
        for check in checks:
            effective_threshold(check, environ)
    except (OSError, ValueError) as exc:
        print(f"alert configuration error: {exc}", file=sys.stderr)
        return ERROR
    url = environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return ERROR
    if connect is None:
        import psycopg

        connect = psycopg.connect
    try:
        with connect(libpq_url(url), connect_timeout=5) as connection:
            connection.read_only = True
            with connection.cursor() as cursor:
                cursor.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
                if not can_see_tenant_rows(cursor):
                    print(
                        "refusing to run: this role cannot bypass row level security, every "
                        "check would read zero rows. Use the administrator or a BYPASSRLS "
                        "monitoring role.",
                        file=sys.stderr,
                    )
                    return ERROR
                outcomes = run_checks(cursor, checks, environ)
    except Exception as exc:  # never echo the URL; exception text may contain it
        print(f"database connection failed ({type(exc).__name__})", file=sys.stderr)
        return ERROR
    for outcome in outcomes:
        print(outcome.line())
    return exit_code(outcomes)


if __name__ == "__main__":
    sys.exit(main())
