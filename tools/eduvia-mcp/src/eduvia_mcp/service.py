"""Deterministic tool behavior, fresh reads, and bounded structured responses."""

import json
import tomllib
from collections import Counter
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from eduvia_mcp.backlog import TRACKERS, load_tasks
from eduvia_mcp.models import (
    BacklogSummary,
    FileContent,
    FileEntry,
    Line,
    Match,
    Overview,
    Page,
    Result,
    Source,
    StackEntry,
    Status,
    Task,
    TaskDetail,
    ToolError,
    Track,
)
from eduvia_mcp.repository import Repository, RepositoryError, fail

# The SDK emits structured data and a text copy. Leave ample space for both,
# JSON escaping, and the JSON-RPC envelope within the 64 KiB response budget.
PAYLOAD_BUDGET = 24 * 1024


def size(value: BaseModel) -> int:
    return len(json.dumps(value.model_dump(mode="json"), ensure_ascii=True).encode())


def clipped[T: BaseModel](value: T) -> tuple[T, bool]:
    """Bound exceptionally long fields while preserving typed IDs and source locations."""
    if size(value) <= PAYLOAD_BUDGET - 1024:
        return value, False
    data = value.model_dump(mode="json")
    changed = False
    while len(json.dumps(data, ensure_ascii=True).encode()) > PAYLOAD_BUDGET - 1024:
        fields: list[tuple[dict, str]] = []
        collections: list[list] = []

        def visit(node: Any, fields=fields, collections=collections) -> None:
            if isinstance(node, dict):
                for key, item in node.items():
                    if key in {"text", "description", "requirement"} and isinstance(item, str):
                        if len(item) > 64:
                            fields.append((node, key))
                    else:
                        visit(item)
            elif isinstance(node, list):
                if node:
                    collections.append(node)
                for item in node:
                    visit(item)

        visit(data)
        if fields:
            parent, key = max(fields, key=lambda pair: len(pair[0][pair[1]]))
            parent[key] = parent[key][: len(parent[key]) // 2] + "…"
        elif collections:
            max(collections, key=lambda items: len(json.dumps(items, ensure_ascii=True))).pop()
        else:
            fail("IO_ERROR", "Result metadata exceeds the response limit.")
        changed = True
    return type(value).model_validate(data), changed


def execute[T: BaseModel](operation: Callable[[], Result[T]]) -> Result[T]:
    try:
        result = operation()
        if result.data is not None:
            result.data, changed = clipped(result.data)
            result.truncated |= changed
        return result
    except RepositoryError as exc:
        return Result(error=ToolError(code=exc.code, message=str(exc)))
    except Exception:
        # Never expose exception text, file contents, absolute paths, or tracebacks.
        return Result(error=ToolError(code="IO_ERROR", message="Repository operation failed."))


def validate_page(offset: int, limit: int) -> None:
    if offset < 0 or not 1 <= limit <= 200:
        fail("INVALID_INPUT", "offset must be nonnegative; limit must be between 1 and 200.")


def page[T: BaseModel](items: list[T], offset: int, limit: int) -> Result[Page[T]]:
    validate_page(offset, limit)
    page_model = Page[type(items[0])] if items else Page[BaseModel]
    chosen = items[offset : offset + limit]
    truncated = offset + len(chosen) < len(items)
    while chosen and size(Page(items=chosen, total=len(items), offset=offset, next_offset=None)) > (
        PAYLOAD_BUDGET - 1024
    ):
        if len(chosen) > 1:
            chosen.pop()
            truncated = True
        else:
            chosen[0], changed = clipped(chosen[0])
            truncated |= changed
            break
    next_offset = offset + len(chosen) if offset + len(chosen) < len(items) else None
    return Result(
        data=page_model(
            items=chosen,
            total=len(items),
            offset=offset,
            next_offset=next_offset,
        ),
        truncated=truncated,
    )


class Tools:
    def __init__(self, repo: Repository):
        self.repo = repo

    def overview(self) -> Result[Overview]:
        def operation():
            backend_path, frontend_path = "backend/pyproject.toml", "frontend/package.json"
            backend_text, frontend_text = (
                self.repo.read(backend_path),
                self.repo.read(frontend_path),
            )
            try:
                backend = tomllib.loads(backend_text)["project"]
                frontend = json.loads(frontend_text)
                requirements = [("Python", backend["requires-python"], backend_path)]
                requirements += [("Node.js", frontend["engines"]["node"], frontend_path)]
                requirements += [
                    (name, version, frontend_path)
                    for name, version in frontend["dependencies"].items()
                ]
                requirements += [
                    (dep.split("==")[0], dep, backend_path) for dep in backend["dependencies"]
                ]
            except (ValueError, KeyError, TypeError):
                fail("PARSE_ERROR", "Project manifests could not be parsed.")
            stack = []
            for name, requirement, source in requirements:
                lines = (
                    backend_text.splitlines()
                    if source == backend_path
                    else (frontend_text.splitlines())
                )
                line = next((n for n, text in enumerate(lines, 1) if requirement in text), 1)
                stack.append(
                    StackEntry(
                        name=name,
                        requirement=requirement,
                        source=Source(path=source, line=line),
                    )
                )
            files = self.repo.files()
            structure = sorted({path.split("/")[0] for path, _ in files})
            documents = [path for path, _ in files if path.endswith(".md")]
            return Result(data=Overview(stack=stack, structure=structure, documents=documents))

        return execute(operation)

    def list_files(self, path: str, offset: int, limit: int) -> Result[Page[FileEntry]]:
        def operation():
            validate_page(offset, limit)
            return page(
                [FileEntry(path=p, size=s) for p, s in self.repo.files(path)], offset, limit
            )

        return execute(operation)

    def read_file(self, path: str, start_line: int, line_count: int) -> Result[FileContent]:
        def operation():
            if start_line < 1 or not 1 <= line_count <= 200:
                fail("INVALID_INPUT", "start_line must be positive; line_count must be 1–200.")
            lines = self.repo.read(path).splitlines()
            selected = [
                Line(number=n, text=text)
                for n, text in enumerate(lines, 1)
                if start_line <= n < start_line + line_count
            ]
            value = FileContent(path=path, lines=selected, total_lines=len(lines), next_line=None)
            while len(value.lines) > 1 and size(value) > PAYLOAD_BUDGET - 1024:
                value.lines.pop()
            value.next_line = (
                value.lines[-1].number + 1
                if value.lines and value.lines[-1].number < len(lines)
                else None
            )
            return Result(data=value, truncated=value.next_line is not None)

        return execute(operation)

    def search(self, query: str, path: str, offset: int, limit: int) -> Result[Page[Match]]:
        def operation():
            validate_page(offset, limit)
            if not query or len(query) > 500 or "\n" in query or "\r" in query:
                fail("INVALID_INPUT", "query must be a single nonempty line up to 500 characters.")
            matches = []
            for name, _ in self.repo.files(path):
                try:
                    text = self.repo.read(name)
                except RepositoryError:
                    continue
                for number, line in enumerate(text.splitlines(), 1):
                    if query in line:
                        # Preserve the vicinity of a hit, even on a huge generated line.
                        position = line.index(query)
                        snippet = line[max(0, position - 120) : position + len(query) + 120]
                        matches.append(Match(path=name, line=number, text=snippet))
            return page(matches, offset, limit)

        return execute(operation)

    def summary(self) -> Result[BacklogSummary]:
        def operation():
            tasks = load_tasks(self.repo)
            return Result(
                data=BacklogSummary(
                    total=len(tasks),
                    by_track=dict(Counter(task.track for task in tasks)),
                    by_status=dict(Counter(task.status for task in tasks)),
                    by_owner=dict(Counter(task.owner for task in tasks)),
                    by_milestone=dict(Counter(task.milestone for task in tasks)),
                    sources=[Source(path=path, line=1) for path in TRACKERS.values()],
                )
            )

        return execute(operation)

    def list_tasks(
        self,
        track: Track | None,
        status: Status | None,
        owner: str | None,
        milestone: str | None,
        query: str | None,
        offset: int,
        limit: int,
    ) -> Result[Page[Task]]:
        def operation():
            validate_page(offset, limit)
            tasks = [
                task
                for task in load_tasks(self.repo)
                if (track is None or task.track == track)
                and (status is None or task.status == status)
                and (owner is None or task.owner == owner)
                and (milestone is None or task.milestone == milestone)
                and (
                    query is None
                    or query.casefold() in (task.id + " " + task.description).casefold()
                )
            ]
            return page(tasks, offset, limit)

        return execute(operation)

    def get_task(self, task_id: str) -> Result[TaskDetail]:
        def operation():
            tasks = load_tasks(self.repo)
            task = next((task for task in tasks if task.id == task_id), None)
            if task is None:
                fail("NOT_FOUND", "Task ID was not found.")
            dependents = [
                item
                for item in tasks
                if any(
                    dep.kind == "task" and dep.identifier == task_id for dep in item.dependencies
                )
            ]
            return Result(data=TaskDetail(task=task, dependents=dependents))

        return execute(operation)
