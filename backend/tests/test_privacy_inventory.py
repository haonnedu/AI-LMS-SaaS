"""PILOT-05 drift guard: the privacy inventory must list every table that stores a person link.

Any table created (or altered) by a migration with an ``email``, ``*user_id`` or ``*student_id``
column must have a row in section 2 of tasks/decisions/0008-privacy-consent-retention.md, and
that row must name each such column. Adding a migration without updating the inventory fails.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "backend" / "migrations" / "versions"
INVENTORY = ROOT / "tasks" / "decisions" / "0008-privacy-consent-retention.md"
PERSON_COLUMN = re.compile(r"(?:\w+_)?user_id|(?:\w+_)?student_id|email")
CREATE_TABLE = re.compile(
    r"CREATE TABLE (?:IF NOT EXISTS )?edu\.(\w+) \((.*?)\n\s*\)(?=;|\s*\"\"\")", re.S
)
ADD_COLUMN = re.compile(r"ALTER TABLE edu\.(\w+)\s+ADD COLUMN (\w+)")
COLUMN_LINE = re.compile(r"^\s*([a-z_]+)\s+[a-zA-Z]", re.M)


def person_columns() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py")):
        text = path.read_text("utf-8")
        for match in CREATE_TABLE.finditer(text):
            columns = {c for c in COLUMN_LINE.findall(match.group(2)) if PERSON_COLUMN.fullmatch(c)}
            if columns:
                found.setdefault(match.group(1), set()).update(columns)
        for table, column in ADD_COLUMN.findall(text):
            if PERSON_COLUMN.fullmatch(column):
                found.setdefault(table, set()).add(column)
    return found


def inventory_rows() -> dict[str, str]:
    text = INVENTORY.read_text("utf-8")
    section = text.split("## 2.", 1)[1].split("\n## 3.", 1)[0]
    rows: dict[str, str] = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        first_cell = line.split("|")[1]
        for table in re.findall(r"`edu\.(\w+)`", first_cell):
            rows[table] = line
    return rows


@pytest.fixture(scope="module")
def columns():
    return person_columns()


def test_scanner_finds_the_known_person_tables(columns):
    # Sanity: if the regex silently stops matching, the drift guard would pass vacuously.
    assert columns["users"] == {"email"}
    assert columns["students"] == {"user_id"}
    assert columns["enrollments"] == {"student_id"}
    assert columns["quiz_attempts"] == {"student_id"}
    assert "personal_owner_user_id" in columns["workspaces"]
    assert {"created_by_user_id", "reviewed_by_user_id"} <= columns["content_revisions"]
    assert len(columns) >= 20


def test_every_person_table_is_inventoried(columns):
    rows = inventory_rows()
    missing = sorted(set(columns) - set(rows))
    assert not missing, f"add these tables to section 2 of {INVENTORY.name}: {missing}"


def test_every_person_column_is_named_in_its_row(columns):
    rows = inventory_rows()
    unnamed = {
        table: sorted(c for c in cols if f"`{c}`" not in rows.get(table, ""))
        for table, cols in columns.items()
    }
    unnamed = {table: cols for table, cols in unnamed.items() if cols}
    assert not unnamed, unnamed


def test_inventory_keeps_the_legal_disclaimer():
    text = INVENTORY.read_text("utf-8")
    assert "Nghị định 13/2023" in text
    assert "không khẳng định Eduvia tuân thủ" in text
    assert "student_consents" in text
