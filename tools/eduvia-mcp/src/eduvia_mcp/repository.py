"""Closed-domain file access shared by every tool. No shell or network access."""

import os
import re
from pathlib import Path, PureWindowsPath

from eduvia_mcp.models import ErrorCode

MAX_FILE_BYTES = 1024 * 1024
ROOT_FILES = {
    "compose.yaml",
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
}
ROOT_DIRS = {"backend", "frontend", "tasks", "contracts", "scripts", "tools", ".github"}
EXTENSIONS = {
    ".md",
    ".py",
    ".toml",
    ".json",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".cjs",
    ".css",
    ".yaml",
    ".yml",
    ".ps1",
    ".ini",
    ".mako",
    ".txt",
    ".lock",
}
SPECIAL_NAMES = {"Dockerfile", ".dockerignore", ".gitignore", "next-env.d.ts"}
EXAMPLE_ENV = {".env.example", "backend/.env.example", "frontend/.env.example"}
BLOCKED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".next",
    "out",
    "build",
    "dist",
    "__pycache__",
    "coverage",
    "htmlcov",
    "tmp",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".cache",
    "playwright-report",
    "test-results",
    ".aws",
    ".ssh",
    ".agents",
    ".agent",
    ".codex",
    ".idea",
    ".vscode",
}
SENSITIVE = re.compile(
    r"(^|[._-])(credentials?|secrets?|tokens?|passwords?|private[-_]?key|id_rsa|id_ed25519)"
    r"([._-]|$)",
    re.I,
)


class RepositoryError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code


def fail(code: ErrorCode, message: str) -> None:
    raise RepositoryError(code, message)


class Repository:
    def __init__(self, root: Path):
        if not root.is_absolute():
            fail("INVALID_INPUT", "repo-root must be an absolute directory.")
        try:
            self.root = root.resolve(strict=True)
        except (OSError, RuntimeError):
            fail("INVALID_INPUT", "repo-root must exist.")
        if not self.root.is_dir():
            fail("INVALID_INPUT", "repo-root must be a directory.")
        for marker in ("frontend/package.json", "backend/pyproject.toml", "tasks/BACKLOG.md"):
            if not self.path(marker).is_file():
                fail("INVALID_INPUT", "repo-root is not an Eduvia checkout.")

    def _relative(self, value: str) -> Path:
        windows = PureWindowsPath(value)
        if (
            not value
            or "\\" in value
            or ":" in value
            or "\x00" in value
            or windows.drive
            or windows.root
            or windows.is_reserved()
            or value.startswith("/")
        ):
            fail("ACCESS_DENIED", "Use a relative repository path with forward slashes.")
        parts = value.split("/")
        if any(part == ".." or part.endswith((" ", ".")) for part in parts if part != "."):
            fail("ACCESS_DENIED", "Path traversal and ambiguous Windows paths are denied.")
        relative = Path(value)
        if relative.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".der", ".crt"}:
            fail("ACCESS_DENIED", "Credential and certificate files are excluded.")
        if any(part.casefold() in BLOCKED_DIRS for part in relative.parts):
            fail("ACCESS_DENIED", "This directory is excluded.")
        if any(part.casefold().endswith(".egg-info") for part in relative.parts):
            fail("ACCESS_DENIED", "Generated package metadata is excluded.")
        if any(SENSITIVE.search(part) for part in relative.parts):
            fail("ACCESS_DENIED", "Sensitive filenames are excluded.")
        if any(part.lower().startswith(".env") for part in relative.parts):
            if relative.as_posix() not in EXAMPLE_ENV:
                fail("ACCESS_DENIED", "Environment files are excluded.")
        if relative.parts:
            first = relative.parts[0]
            if first not in ROOT_DIRS and not (
                len(relative.parts) == 1
                and (
                    first in ROOT_FILES
                    or relative.suffix == ".md"
                    or relative.as_posix() in EXAMPLE_ENV
                )
            ):
                fail("ACCESS_DENIED", "Path is outside the allowed source directories.")
        return relative

    def path(self, value: str = ".") -> Path:
        relative = self._relative(value)
        candidate = self.root / relative
        try:
            # Reject all symlinks/junctions, including aliases to an allowed internal file.
            current = self.root
            for part in relative.parts:
                current = current / part
                if current.is_symlink() or current.is_junction():
                    fail("ACCESS_DENIED", "Symbolic links and junctions are excluded.")
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(self.root):
                fail("ACCESS_DENIED", "Path leaves the repository.")
        except FileNotFoundError:
            fail("NOT_FOUND", "Repository path does not exist.")
        except (OSError, RuntimeError):
            fail("ACCESS_DENIED", "Repository path cannot be accessed.")
        if resolved.is_file() and not self._text_name(relative):
            fail("ACCESS_DENIED", "File type is not allowed.")
        return resolved

    @staticmethod
    def _text_name(relative: Path) -> bool:
        return (
            relative.suffix in EXTENSIONS
            or relative.name in SPECIAL_NAMES
            or relative.as_posix() in EXAMPLE_ENV
            or relative.as_posix() in ROOT_FILES
        )

    def read(self, value: str) -> str:
        target = self.path(value)
        if not target.is_file():
            fail("INVALID_INPUT", "Expected a text file.")
        try:
            if target.stat().st_size > MAX_FILE_BYTES:
                fail("ACCESS_DENIED", "File exceeds the 1 MiB read limit.")
            with target.open("rb") as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
            if len(raw) > MAX_FILE_BYTES:
                fail("ACCESS_DENIED", "File exceeds the 1 MiB read limit.")
            text = raw.decode("utf-8-sig")
            if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
                fail("ACCESS_DENIED", "Binary or control-character content is excluded.")
            return text
        except UnicodeError:
            fail("ACCESS_DENIED", "Only UTF-8 text is supported.")
        except OSError:
            fail("IO_ERROR", "Repository file could not be read.")

    def files(self, value: str = ".") -> list[tuple[str, int]]:
        start = self.path(value)
        candidates = []
        if start.is_file():
            candidates.append(start)
        else:
            for directory, dirs, files in os.walk(start, followlinks=False):
                allowed = []
                for name in sorted(dirs):
                    try:
                        self.path((Path(directory) / name).relative_to(self.root).as_posix())
                        allowed.append(name)
                    except RepositoryError:
                        continue
                dirs[:] = allowed
                candidates.extend(Path(directory) / name for name in sorted(files))
        result = []
        for candidate in candidates:
            relative = candidate.relative_to(self.root).as_posix()
            try:
                # Reading as well as checking the extension excludes disguised binary files.
                self.read(relative)
                result.append((relative, self.path(relative).stat().st_size))
            except (RepositoryError, OSError):
                continue
        return sorted(result)
