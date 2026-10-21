import os
import subprocess

import pytest

from eduvia_mcp.repository import MAX_FILE_BYTES, Repository, RepositoryError


@pytest.mark.parametrize(
    "path",
    [
        "../README.md",
        "frontend/../../README.md",
        "/etc/passwd",
        "C:/Windows/win.ini",
        r"C:\Windows\win.ini",
        r"\\server\share\file.md",
        "frontend/x.py:stream",
        "frontend/CON.py",
        "frontend/NUL.txt",
        "frontend/../backend/pyproject.toml",
        "frontend./x.py",
        "frontend /x.py",
        "\x00",
        ".env",
        "backend/.env",
        "frontend/.env.local",
        "frontend/.env.production",
        "backend/.ENV",
        "backend/secrets.json",
        "backend/credentials.json",
        "backend/private-key.txt",
        ".git/config",
        "frontend/node_modules/x.ts",
        "backend/.venv/x.py",
        "backend/.pytest-tmp/example.md",
        "backend/cache.pem",
        "random/file.py",
    ],
)
def test_denies_paths(repo, path):
    with pytest.raises(RepositoryError) as error:
        repo.read(path)
    assert error.value.code == "ACCESS_DENIED"


def test_allowlisted_environment_examples(checkout, repo):
    for path in (".env.example", "backend/.env.example", "frontend/.env.example"):
        (checkout / path).write_text("APP_ENV=development", encoding="utf-8")
        assert "development" in repo.read(path)
    (checkout / "backend/.env.custom.example").write_text("SECRET", encoding="utf-8")
    with pytest.raises(RepositoryError):
        repo.read("backend/.env.custom.example")


def test_binary_large_and_excluded_files_not_listed(checkout, repo):
    (checkout / "backend/binary.py").write_bytes(b"abc\x00def")
    (checkout / "backend/non_utf8.py").write_bytes(b"\xff\xfe")
    (checkout / "backend/big.md").write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    (checkout / "backend/.env").write_text("DO_NOT_LEAK", encoding="utf-8")
    names = {path for path, _ in repo.files()}
    assert "backend/pyproject.toml" in names
    assert not names & {
        "backend/binary.py",
        "backend/non_utf8.py",
        "backend/big.md",
        "backend/.env",
    }
    for path in ("backend/binary.py", "backend/non_utf8.py", "backend/big.md"):
        with pytest.raises(RepositoryError) as error:
            repo.read(path)
        assert error.value.code == "ACCESS_DENIED"


def test_missing_file_and_invalid_root(checkout, repo):
    with pytest.raises(RepositoryError) as error:
        repo.read("backend/missing.py")
    assert error.value.code == "NOT_FOUND"
    with pytest.raises(RepositoryError):
        Repository(checkout / "missing")
    with pytest.raises(RepositoryError):
        Repository(type(checkout)("relative"))


def test_symlink_aliases_are_denied(checkout, repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "private.md"
    outside.write_text("DO_NOT_LEAK", encoding="utf-8")
    for name, target in (
        ("outside.md", outside),
        ("inside.md", checkout / "backend/pyproject.toml"),
    ):
        alias = checkout / "backend" / name
        try:
            alias.symlink_to(target)
        except OSError:
            pytest.skip("Windows symlinks require Developer Mode or elevated permissions")
        with pytest.raises(RepositoryError) as error:
            repo.read(f"backend/{name}")
        assert error.value.code == "ACCESS_DENIED"
        assert f"backend/{name}" not in dict(repo.files())


@pytest.mark.skipif(os.name != "nt", reason="NTFS junction test")
def test_windows_junctions_are_denied(checkout, repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("junction-target")
    (outside / "private.md").write_text("DO_NOT_LEAK", encoding="utf-8")
    alias = checkout / "backend/junction"
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(alias), str(outside)],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    try:
        with pytest.raises(RepositoryError):
            repo.read("backend/junction/private.md")
        assert not any("junction" in path for path, _ in repo.files())
    finally:
        # Remove only the link itself; never recurse into its target.
        alias.rmdir()
