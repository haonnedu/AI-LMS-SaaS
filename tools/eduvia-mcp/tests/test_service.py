import json

import pytest

from eduvia_mcp.service import PAYLOAD_BUDGET, size


def test_file_pagination_and_fresh_reads(checkout, tools):
    target = checkout / "backend/example.py"
    target.write_text("first\nsecond\nthird\n", encoding="utf-8")
    result = tools.read_file("backend/example.py", 2, 1)
    assert [(line.number, line.text) for line in result.data.lines] == [(2, "second")]
    assert result.data.next_line == 3
    assert result.truncated
    target.write_text("changed", encoding="utf-8")
    assert tools.read_file("backend/example.py", 1, 200).data.lines[0].text == "changed"
    result = tools.read_file("backend/example.py", 20, 200)
    assert result.data.lines == []
    assert result.data.next_line is None
    files = tools.list_files(".", 0, 1)
    assert files.data.next_offset == 1
    assert files.data.items[0].path < tools.list_files(".", 1, 1).data.items[0].path


def test_literal_search_and_secret_exclusion(checkout, tools):
    (checkout / "backend/example.py").write_text("a.*b\nacb\na.*b", encoding="utf-8")
    (checkout / "backend/.env").write_text("a.*b DO_NOT_LEAK", encoding="utf-8")
    result = tools.search("a.*b", ".", 0, 1)
    assert result.data.total == 2
    assert result.data.items[0].line == 1
    assert result.data.next_offset == 1
    assert "DO_NOT_LEAK" not in result.model_dump_json()
    assert tools.search("A.*B", ".", 0, 50).data.total == 0


@pytest.mark.parametrize("offset,limit", [(-1, 50), (0, 0), (0, 201)])
def test_invalid_pagination(tools, offset, limit):
    assert tools.list_files(".", offset, limit).error.code == "INVALID_INPUT"
    assert tools.search("test", ".", offset, limit).error.code == "INVALID_INPUT"


def test_invalid_line_and_query_inputs(tools):
    assert tools.read_file("tasks/BACKLOG.md", 0, 20).error.code == "INVALID_INPUT"
    assert tools.read_file("tasks/BACKLOG.md", 1, 201).error.code == "INVALID_INPUT"
    assert tools.search("", ".", 0, 50).error.code == "INVALID_INPUT"
    assert tools.search("x\ny", ".", 0, 50).error.code == "INVALID_INPUT"


def test_long_unicode_responses_are_bounded(checkout, tools):
    (checkout / "backend/long.py").write_text("Việt Nam " * 15000, encoding="utf-8")
    result = tools.read_file("backend/long.py", 1, 200)
    assert result.truncated
    assert size(result) < PAYLOAD_BUDGET
    assert result.data.lines[0].number == 1
    assert result.data.lines[0].text.endswith("…")


def test_response_budget_preserves_pagination(checkout, tools):
    # Keep this fixture under the file-size limit.
    (checkout / "backend/lines.py").write_text(
        "\n".join("Việt " * 100 for _ in range(200)),
        encoding="utf-8",
    )
    result = tools.read_file("backend/lines.py", 1, 200)
    assert result.truncated
    assert size(result) < PAYLOAD_BUDGET
    assert result.data.next_line == result.data.lines[-1].number + 1
    next_page = tools.read_file("backend/lines.py", result.data.next_line, 200)
    assert next_page.data.lines[0].number == result.data.next_line


def test_overview_is_manifest_derived(checkout, tools):
    result = tools.overview()
    assert result.error is None
    next_entry = next(item for item in result.data.stack if item.name == "next")
    assert next_entry.requirement == "16.4.2"
    data = json.loads((checkout / "frontend/package.json").read_text(encoding="utf-8"))
    data["dependencies"]["next"] = "future-version"
    (checkout / "frontend/package.json").write_text(json.dumps(data), encoding="utf-8")
    assert any(item.requirement == "future-version" for item in tools.overview().data.stack)


def test_errors_do_not_expose_exception_details(tools, monkeypatch):
    def broken(_):
        raise RuntimeError("DO_NOT_LEAK")

    monkeypatch.setattr(tools.repo, "read", broken)
    result = tools.read_file("backend/example.py", 1, 10)
    assert result.error.code == "IO_ERROR"
    assert "DO_NOT_LEAK" not in result.model_dump_json()


def test_task_pages_do_not_skip_when_budget_reduces_limit(checkout, tools):
    with (checkout / "tasks/CORE.md").open("a", encoding="utf-8") as stream:
        for number in range(1, 31):
            stream.write(f"| BASE-{number:02d} | todo | — | — | " + "Việt Nam " * 150 + " |\n")
    found, offset = [], 0
    while True:
        result = tools.list_tasks(None, None, None, None, None, offset, 200)
        assert result.error is None
        assert size(result) < PAYLOAD_BUDGET
        found.extend(task.id for task in result.data.items)
        if result.data.next_offset is None:
            break
        assert result.data.next_offset > offset
        offset = result.data.next_offset
    assert found == [f"BASE-{number:02d}" for number in range(1, 31)]
