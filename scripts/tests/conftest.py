import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def verifier(monkeypatch, tmp_path):
    path = Path(__file__).parents[1] / "verify-m0.py"
    spec = importlib.util.spec_from_file_location("m0_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module.Verification, "git", lambda self, *args: "fixture-source")
    return module
