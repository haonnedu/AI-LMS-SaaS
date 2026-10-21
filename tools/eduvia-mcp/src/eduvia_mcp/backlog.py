"""Parse the four authoritative trackers, without inferring delivery readiness."""

import re

from eduvia_mcp.models import Dependency, Source, Task, Track
from eduvia_mcp.repository import Repository, fail

TRACKERS: dict[Track, str] = {
    "core": "tasks/CORE.md",
    "school": "tasks/SCHOOL.md",
    "student": "tasks/STUDENT.md",
    "omr_billing": "tasks/OMR_BILLING.md",
}
STATUSES = {"todo", "ready", "in_progress", "review", "blocked", "done", "cancelled"}
TASK_ID = re.compile(r"[A-Z][A-Z0-9]*-\d+(?:[a-z])?|M\d+-QA")
GATE = re.compile(r"[MHL]\d+")


def cells(line: str) -> list[str]:
    """Split pipes with Markdown backslash escaping (including escaped backslashes)."""
    result, current = [], []
    position = 0
    value = line.strip()
    while position < len(value):
        char = value[position]
        if char == "\\" and position + 1 < len(value) and value[position + 1] in "\\|":
            current.append(value[position + 1])
            position += 2
            continue
        if char == "|":
            result.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        position += 1
    result.append("".join(current).strip())
    return result[1:-1] if value.startswith("|") and value.endswith("|") else result


def load_tasks(repo: Repository) -> list[Task]:
    tasks: list[Task] = []
    ids: set[str] = set()
    gates: set[str] = set()
    for track, path in TRACKERS.items():
        heading, active, fenced = "", False, False
        for number, line in enumerate(repo.read(path).splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                fenced = not fenced
                continue
            if fenced:
                continue
            if re.match(r"#{1,6}\s", stripped):
                heading = stripped.lstrip("#").strip()
                gate = re.match(r"([MHL]\d+)\b", heading)
                if gate:
                    gates.add(gate[1])
                active = False
                continue
            if not stripped.startswith("|"):
                if active and "|" in stripped and TASK_ID.match(stripped):
                    fail("PARSE_ERROR", f"Invalid task row at {path}:{number}.")
                if stripped:
                    active = False
                continue
            row = cells(stripped)
            if row and row[0] == "ID":
                if row[:4] != ["ID", "Trạng thái", "Owner", "Phụ thuộc"] or len(row) != 5:
                    fail("PARSE_ERROR", f"Invalid task table header at {path}:{number}.")
                active = True
                continue
            if not active:
                continue
            if row and all(re.fullmatch(r":?-+:?", cell) for cell in row):
                continue
            if len(row) != 5 or not TASK_ID.fullmatch(row[0]) or row[1] not in STATUSES:
                fail("PARSE_ERROR", f"Invalid task row at {path}:{number}.")
            identifier, status, owner, raw_dependencies, description = row
            if identifier in ids:
                fail("PARSE_ERROR", f"Duplicate task ID at {path}:{number}.")
            if not owner or not description or not heading or not raw_dependencies:
                fail("PARSE_ERROR", f"Incomplete task row at {path}:{number}.")
            ids.add(identifier)
            dependencies = []
            if raw_dependencies not in {"—", "-"}:
                for token in re.split(r"[,;]", raw_dependencies):
                    token = token.strip()
                    if not token:
                        fail("PARSE_ERROR", f"Empty dependency at {path}:{number}.")
                    kind = (
                        "gate"
                        if GATE.fullmatch(token)
                        else ("task" if TASK_ID.fullmatch(token) else "unknown")
                    )
                    dependencies.append(Dependency(identifier=token, kind=kind, resolved=False))
            gate = re.match(r"([MHL]\d+)\b", heading)
            tasks.append(
                Task(
                    id=identifier,
                    track=track,
                    milestone=gate[1] if gate else heading,
                    status=status,
                    owner=owner,
                    dependencies=dependencies,
                    description=description,
                    source=Source(path=path, line=number),
                )
            )
    for task in tasks:
        for dependency in task.dependencies:
            dependency.resolved = dependency.identifier in (
                gates if dependency.kind == "gate" else ids if dependency.kind == "task" else set()
            )
    return tasks
