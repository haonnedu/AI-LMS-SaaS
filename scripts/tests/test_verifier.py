import json
import subprocess

import pytest


@pytest.mark.parametrize("project", ["eduvia", "", "other-project", "eduvia-m0-../eduvia"])
def test_rejects_other_projects_before_subprocess(verifier, monkeypatch, project):
    check = verifier.Verification()
    check.project = project
    monkeypatch.setattr(verifier.subprocess, "run", lambda *a, **k: pytest.fail("Docker called"))
    with pytest.raises(ValueError):
        check.compose("down", "--volumes")


def test_environment_cannot_override_isolated_stack(verifier, monkeypatch):
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "eduvia")
    monkeypatch.setenv("COMPOSE_FILE", "production.yaml")
    monkeypatch.setenv("POSTGRES_PASSWORD", "existing-secret")
    monkeypatch.setenv("API_PORT", "8000")
    monkeypatch.setenv("PATH", "keep-tool-path")
    env = verifier.isolated_environment({"POSTGRES_PASSWORD": "new", "API_PORT": "new"})
    assert "COMPOSE_PROJECT_NAME" not in env
    assert "COMPOSE_FILE" not in env
    assert "POSTGRES_PASSWORD" not in env
    assert "API_PORT" not in env
    assert env["COMPOSE_DISABLE_ENV_FILE"] == "1"
    assert env["PATH"] == "keep-tool-path"


def test_report_ports_do_not_include_credentials(verifier):
    check = verifier.Verification()
    assert set(check.report["ports"]) == set(verifier.PORT_NAMES)
    assert len(set(check.report["ports"].values())) == 4
    assert check.values["POSTGRES_PASSWORD"] not in json.dumps(check.report)


@pytest.mark.parametrize("heads", [[], ["one", "two"], "one", [None]])
def test_rejects_missing_or_ambiguous_heads(verifier, monkeypatch, heads):
    check = verifier.Verification()
    monkeypatch.setattr(check, "compose", lambda *args: json.dumps(heads))
    with pytest.raises(RuntimeError, match="exactly one"):
        check.expected_head()


def test_wrong_revision_and_tables_fail(verifier, monkeypatch):
    check = verifier.Verification()
    monkeypatch.setattr(check, "sql", lambda query: "0001_bootstrap")
    with pytest.raises(RuntimeError, match="revision"):
        check.revision("future_head")
    monkeypatch.setattr(check, "sql", lambda query: "users\nworkspaces")
    with pytest.raises(RuntimeError, match="tables"):
        check.tables(verifier.IDENTITY_TABLES)


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_compose_redacts_diagnostics_and_has_timeout(verifier, monkeypatch, failure):
    check = verifier.Verification()
    secret = check.values["POSTGRES_PASSWORD"]

    def execute(args, **kwargs):
        assert kwargs["timeout"] == 180
        assert kwargs["check"] is False
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 180, output=secret.encode(), stderr=secret)
        return subprocess.CompletedProcess(args, 1, secret, secret)

    monkeypatch.setattr(verifier.subprocess, "run", execute)
    with pytest.raises(RuntimeError) as error:
        check.compose("up", secret)
    log = (check.directory / "commands.log").read_text(encoding="utf-8")
    assert secret not in log + str(error.value)
    assert "[REDACTED]" in log


def scenario(verifier, monkeypatch, fail_step=None, fail_cleanup=False, timeout=False):
    check = verifier.Verification()
    state = {"revision": "", "tables": [], "schema": "1", "vector": "1"}
    calls = []

    def compose(*args):
        calls.append(args)
        if args[0] == "down":
            if fail_cleanup:
                raise RuntimeError("cleanup failed " + check.values["POSTGRES_PASSWORD"])
            return ""
        if check.report["step"] == fail_step:
            if timeout:
                raise subprocess.TimeoutExpired(args, 180)
            raise RuntimeError("injected failure " + check.values["POSTGRES_PASSWORD"])
        if "python" in args and "-c" in args:
            return '["future_head"]'
        if args[0] == "run":
            if "downgrade" in args:
                raise RuntimeError("forward-only migration")
            elif "0001_bootstrap" in args:
                state.update(revision="0001_bootstrap", tables=[], schema="1", vector="1")
            else:
                state.update(revision="future_head", tables=verifier.IDENTITY_TABLES, schema="1")
        return ""

    def sql(query):
        if "schemata" in query:
            return state["schema"]
        if "pg_extension" in query:
            return state["vector"]
        if "pg_tables" in query:
            return "\n".join(state["tables"])
        if "count(*) FROM alembic_version" in query:
            return "0" if not state["revision"] else "1"
        if "version_num" in query:
            return state["revision"]
        pytest.fail(f"Unexpected SQL: {query}")

    def wait(url, status, checks=None, **kwargs):
        if status == 503:
            return '{"error":{"code":"backend_unavailable"}}'
        if "/api/backend/health" in url:
            return '{"service":"eduvia-api"}'
        return "Eduvia"

    monkeypatch.setattr(check, "compose", compose)
    monkeypatch.setattr(check, "sql", sql)
    monkeypatch.setattr(verifier, "wait_http", wait)
    return check, calls


def test_full_lifecycle_uses_discovered_head_and_cleans_up(verifier, monkeypatch):
    check, calls = scenario(verifier, monkeypatch)
    check.run()
    report = json.loads((check.directory / "result.json").read_text())
    assert report["result"] == "passed"
    assert report["expected_head"] == "future_head"
    assert report["observed_tables"] == verifier.IDENTITY_TABLES
    assert any("downgrade" in call for call in calls)
    assert calls[-1][0] == "down"
    assert not check.env_file.exists()


@pytest.mark.parametrize("step", ["build", "upgrade-head", "outage-db"])
def test_failure_still_cleans_up_and_saves_sanitized_report(verifier, monkeypatch, step):
    check, calls = scenario(verifier, monkeypatch, fail_step=step)
    with pytest.raises(RuntimeError, match="Verification or cleanup failed"):
        check.run()
    report_text = (check.directory / "result.json").read_text()
    report = json.loads(report_text)
    assert report["failed_step"] == step
    assert report["result"] == "failed"
    assert check.values["POSTGRES_PASSWORD"] not in report_text
    assert calls[-1][0] == "down"
    assert not check.env_file.exists()


def test_cleanup_failure_cannot_be_reported_as_success(verifier, monkeypatch):
    check, _ = scenario(verifier, monkeypatch, fail_cleanup=True)
    with pytest.raises(RuntimeError):
        check.run()
    report = json.loads((check.directory / "result.json").read_text())
    assert report["result"] == "failed"
    assert report["failed_step"] == "cleanup"
    assert "FAILED" in report["cleanup"]
    assert check.values["POSTGRES_PASSWORD"] not in json.dumps(report)
    assert not check.env_file.exists()


def test_timeout_still_attempts_cleanup(verifier, monkeypatch):
    check, calls = scenario(verifier, monkeypatch, fail_step="build", timeout=True)
    with pytest.raises(RuntimeError):
        check.run()
    report = json.loads((check.directory / "result.json").read_text())
    assert report["result"] == "failed"
    assert report["failed_step"] == "build"
    assert calls[-1][0] == "down"
    assert not check.env_file.exists()
