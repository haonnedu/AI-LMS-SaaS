"""Regression: tmp_path must work on the first run, before pytest creates its cache."""

import subprocess
import sys


def test_temp_directory_works_on_fresh_checkout(tmp_path, real_root):
    package = real_root / "tools/eduvia-mcp"
    fresh = tmp_path / "fresh-checkout"
    (fresh / "tests").mkdir(parents=True)
    (fresh / "pyproject.toml").write_text(
        (package / "pyproject.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (fresh / "tests/test_temp.py").write_text(
        "def test_temp(tmp_path):\n    assert tmp_path.is_dir()\n",
        encoding="utf-8",
    )
    assert not (fresh / ".pytest_cache").exists()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=fresh,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
