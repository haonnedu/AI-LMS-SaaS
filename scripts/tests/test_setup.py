import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows setup compatibility")


@pytest.fixture(params=["powershell.exe", "pwsh.exe"])
def shell(request):
    executable = shutil.which(request.param)
    if not executable:
        pytest.fail(f"Required Windows shell missing: {request.param}")
    return executable


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout with spaces"
    (root / "scripts").mkdir(parents=True)
    shutil.copyfile(Path(__file__).parents[1] / "setup.ps1", root / "scripts/setup.ps1")
    return root


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def invoke(shell, checkout, *args):
    return subprocess.run(
        [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(checkout / "scripts/setup.ps1"),
            "-CheckOnly",
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        cwd=checkout,
    )


def test_explicit_python_check_only_does_not_write(shell, checkout):
    before = snapshot(checkout)
    result = invoke(shell, checkout, "-Python312", sys.executable)
    assert result.returncode == 0, result.stderr
    assert "validation passed" in result.stdout
    assert snapshot(checkout) == before
    assert not (checkout / "backend").exists()


@pytest.mark.parametrize("candidate", ["relative.exe", "Z:/missing/python.exe"])
def test_missing_or_relative_python_is_rejected(shell, checkout, candidate):
    before = snapshot(checkout)
    result = invoke(shell, checkout, "-Python312", candidate)
    assert result.returncode != 0
    assert "existing absolute" in result.stderr
    assert snapshot(checkout) == before


@pytest.mark.parametrize("version", ["3.11", "3.13", ""])
def test_wrong_python_version_is_rejected(shell, checkout, version):
    # Controlled interpreter fixture: the real 3.12 success path is tested separately.
    interpreter = checkout / "version fixture.cmd"
    interpreter.write_text(
        f"@echo off\n{'echo ' + version if version else 'rem no output'}\nexit /b 0\n"
    )
    before = snapshot(checkout)
    result = invoke(shell, checkout, "-Python312", str(interpreter))
    assert result.returncode != 0
    assert "Python 3.12 is required" in result.stderr
    assert snapshot(checkout) == before


def test_existing_unusable_venv_is_preserved(shell, checkout):
    interpreter = checkout / "backend/.venv/Scripts/python.exe"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"not an executable")
    before = snapshot(checkout)
    result = invoke(shell, checkout, "-Python312", sys.executable)
    assert result.returncode != 0
    assert "Python 3.12 is required" in result.stderr
    assert snapshot(checkout) == before


def test_existing_312_venv_is_detected_without_explicit_path(shell, checkout):
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(checkout / "backend/.venv")],
        check=True,
        capture_output=True,
        timeout=30,
    )
    before = snapshot(checkout)
    result = invoke(shell, checkout)
    assert result.returncode == 0, result.stderr
    assert snapshot(checkout) == before
