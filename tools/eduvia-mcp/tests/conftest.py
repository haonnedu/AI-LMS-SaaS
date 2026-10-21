import json
from pathlib import Path

import pytest

from eduvia_mcp.repository import Repository
from eduvia_mcp.service import Tools

HEADER = "| ID | Trạng thái | Owner | Phụ thuộc | Task / nghiệm thu |\n|---|---|---|---|---|\n"


@pytest.fixture
def checkout(tmp_path):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend").mkdir()
    (tmp_path / "tasks").mkdir()
    (tmp_path / "frontend/package.json").write_text(
        json.dumps(
            {
                "engines": {"node": ">=24 <25"},
                "dependencies": {"next": "16.4.2"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "backend/pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.12"\ndependencies = ["fastapi==0.148.0"]\n',
        encoding="utf-8",
    )
    (tmp_path / "tasks/BACKLOG.md").write_text("# Quy ước\n", encoding="utf-8")
    for name, milestone in (
        ("CORE", "M0"),
        ("SCHOOL", "H0"),
        ("STUDENT", "L0"),
        ("OMR_BILLING", "A. OMR"),
    ):
        (tmp_path / f"tasks/{name}.md").write_text(
            f"## {milestone} — Kế hoạch\n\n" + HEADER,
            encoding="utf-8",
        )
    return tmp_path


@pytest.fixture
def repo(checkout):
    return Repository(checkout)


@pytest.fixture
def tools(repo):
    return Tools(repo)


@pytest.fixture
def real_root():
    return Path(__file__).resolve().parents[3]
