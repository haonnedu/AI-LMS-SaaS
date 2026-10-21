import pytest

from eduvia_mcp.backlog import cells, load_tasks
from eduvia_mcp.repository import Repository, RepositoryError
from eduvia_mcp.service import Tools


def append(root, text, name="CORE"):
    with (root / f"tasks/{name}.md").open("a", encoding="utf-8") as stream:
        stream.write(text + "\n")


def test_actual_backlog_baseline(real_root):
    result = Tools(Repository(real_root)).summary()
    assert result.error is None
    assert result.data.total == 179
    assert result.data.by_track == {"core": 92, "school": 25, "student": 28, "omr_billing": 34}
    assert result.data.by_status == {"todo": 179}
    assert result.data.by_owner == {"—": 179}


def test_escaped_pipe_and_backslash():
    assert cells(r"| a | Nội dung \| ghi chú |") == ["a", "Nội dung | ghi chú"]
    assert cells(r"| a | path\\ |") == ["a", "path\\"]


def test_dependencies_filters_and_fresh_reads(checkout, tools):
    append(checkout, r"| BASE-01 | todo | An | — | Kiểm tra \| tiếng Việt |")
    append(checkout, "| BASE-02 | blocked | Bình | BASE-01; M0, M9, MISSING-99 | Công việc |")
    detail = tools.get_task("BASE-01").data
    assert detail.task.description == "Kiểm tra | tiếng Việt"
    assert detail.task.milestone == "M0"
    assert detail.task.source.line == 5
    assert [item.id for item in detail.dependents] == ["BASE-02"]
    dependencies = tools.get_task("BASE-02").data.task.dependencies
    assert [(dep.kind, dep.resolved) for dep in dependencies] == [
        ("task", True),
        ("gate", True),
        ("gate", False),
        ("task", False),
    ]
    result = tools.list_tasks("core", "todo", "An", "M0", "TIẾNG VIỆT", 0, 50)
    assert result.data.total == 1
    append(checkout, "| BASE-03 | review | An | — | Thêm mới |")
    assert tools.summary().data.total == 3
    assert tools.get_task("MISSING-01").error.code == "NOT_FOUND"


@pytest.mark.parametrize(
    "row",
    [
        "| BASE-01 | invalid | — | — | Sai trạng thái |",
        "| BASE-01 | todo | — | — | thiếu | thêm cột |",
        "| invalid | todo | — | — | Sai ID |",
        "| BASE-01 | todo | | — | Thiếu owner |",
        "| BASE-01 | todo | — | M0, | Dependency rỗng |",
        "BASE-01 | todo | — | — | Thiếu pipe đầu dòng |",
    ],
)
def test_invalid_rows_fail_closed(checkout, tools, row):
    append(checkout, row)
    result = tools.summary()
    assert result.data is None
    assert result.error.code == "PARSE_ERROR"
    assert "tasks/CORE.md:5" in result.error.message
    assert row not in result.error.message


def test_duplicate_across_trackers(checkout, repo):
    row = "| BASE-01 | todo | — | — | Trùng |"
    append(checkout, row)
    append(checkout, row, "SCHOOL")
    with pytest.raises(RepositoryError, match="Duplicate"):
        load_tasks(repo)


def test_ignores_non_task_tables_and_fences(checkout, tools):
    append(checkout, "\n## Quy ước\n| Trạng thái | Ý nghĩa |\n| todo | Chưa làm |")
    append(checkout, "\n```markdown\n| ID | bogus |\n```\n")
    assert tools.summary().data.total == 0


def test_malformed_task_header(checkout, tools):
    append(checkout, "\n| ID | Status | Owner | Depends | Description |")
    assert tools.summary().error.code == "PARSE_ERROR"
