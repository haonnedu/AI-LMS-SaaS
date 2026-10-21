import asyncio
import json
import os
import subprocess
import sys

import pytest
from jsonschema import validate
from mcp import Client
from mcp.client.stdio import StdioServerParameters

EXPECTED = {
    "get_project_overview",
    "list_files",
    "read_file",
    "search_source",
    "get_backlog_summary",
    "list_tasks",
    "get_task",
}


def test_stdio_handshake_tools_and_results(real_root):
    async def scenario():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "eduvia_mcp.server", "--repo-root", str(real_root)],
            cwd=str(real_root / "frontend"),  # root is independent of client cwd
        )
        async with asyncio.timeout(30):
            async with Client(parameters, mode="legacy") as client:
                catalog = await client.list_tools()
                assert {tool.name for tool in catalog.tools} == EXPECTED
                schemas = {tool.name: tool.output_schema for tool in catalog.tools}
                for tool in catalog.tools:
                    assert tool.annotations.read_only_hint is True
                    assert tool.annotations.destructive_hint is False
                    assert tool.annotations.open_world_hint is False
                    assert tool.input_schema["type"] == "object"
                    assert tool.output_schema is not None
                calls = {
                    "get_project_overview": {},
                    "list_files": {"path": "backend/app", "limit": 2},
                    "read_file": {"path": "README.md", "line_count": 2},
                    "search_source": {"query": "create_app", "path": "backend/app"},
                    "get_backlog_summary": {},
                    "list_tasks": {"track": "core", "milestone": "M0", "limit": 2},
                    "get_task": {"task_id": "BASE-01"},
                }
                for name, arguments in calls.items():
                    result = await client.call_tool(name, arguments)
                    assert not result.is_error
                    validate(result.structured_content, schemas[name])
                    assert result.structured_content["error"] is None
                    # Include both SDK content channels and JSON escaping in the budget.
                    wire = json.dumps(result.model_dump(mode="json", by_alias=True))
                    assert len(wire.encode()) < 64 * 1024
                    if name == "get_backlog_summary":
                        summary = result.structured_content["data"]
                        assert summary["total"] > 0
                        for group in ("by_track", "by_status", "by_owner", "by_milestone"):
                            assert sum(summary[group].values()) == summary["total"]
                denied = await client.call_tool("read_file", {"path": "backend/.env"})
                assert denied.structured_content["error"]["code"] == "ACCESS_DENIED"
                invalid = await client.call_tool("list_files", {"limit": 201})
                assert invalid.structured_content["error"]["code"] == "INVALID_INPUT"

    asyncio.run(scenario())


def test_protocol_stdout_is_only_json_and_shutdown_is_clean(real_root):
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "stdout-check", "version": "1"},
        },
    }
    process = subprocess.run(
        [sys.executable, "-m", "eduvia_mcp.server", "--repo-root", str(real_root)],
        input=json.dumps(message) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert process.returncode == 0
    lines = process.stdout.splitlines()
    assert lines
    assert all(isinstance(json.loads(line), dict) for line in lines)
    assert any(json.loads(line).get("id") == 1 for line in lines)
    assert "Traceback" not in process.stderr


def test_invalid_root_exits_without_stdout(checkout):
    process = subprocess.run(
        [sys.executable, "-m", "eduvia_mcp.server", "--repo-root", str(checkout / "missing")],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 2
    assert process.stdout == ""
    assert "Traceback" not in process.stderr


@pytest.mark.skipif(os.name != "nt", reason="PowerShell launcher on Windows")
def test_windows_launcher_resolves_root_from_other_cwd(real_root):
    process = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(real_root / "tools/eduvia-mcp/scripts/start.ps1"),
        ],
        input="",
        capture_output=True,
        text=True,
        timeout=20,
        cwd=real_root / "frontend",
    )
    assert process.returncode == 0
    assert process.stdout == ""
    assert "Traceback" not in process.stderr


def test_large_results_fit_wire_budget(checkout):
    (checkout / "backend/long.py").write_text(
        "\n".join("Việt Nam " * 100 for _ in range(200)),
        encoding="utf-8",
    )
    (checkout / "backend/single.py").write_text("Việt Nam " * 10000, encoding="utf-8")
    with (checkout / "tasks/CORE.md").open("a", encoding="utf-8") as stream:
        for number in range(1, 101):
            stream.write(f"| BASE-{number:02d} | todo | — | — | " + "Việt Nam " * 80 + " |\n")

    async def scenario():
        async with asyncio.timeout(30):
            async with Client(
                StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "eduvia_mcp.server", "--repo-root", str(checkout)],
                )
            ) as client:
                for name, arguments in [
                    ("read_file", {"path": "backend/long.py"}),
                    ("read_file", {"path": "backend/single.py"}),
                    ("list_tasks", {"limit": 200}),
                    ("search_source", {"query": "Việt", "limit": 200}),
                ]:
                    result = await client.call_tool(name, arguments)
                    assert not result.is_error
                    assert result.structured_content["error"] is None
                    assert result.structured_content["truncated"]
                    wire = json.dumps(result.model_dump(mode="json", by_alias=True))
                    assert len(wire.encode()) < 64 * 1024

    asyncio.run(scenario())
