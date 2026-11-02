import json

from typer.testing import CliRunner

from sessions_manager.cli import app
from sessions_manager.models import Failure

runner = CliRunner()


def test_help_and_version_do_not_create_state(isolated):
    config, data = isolated
    for flag in ("--help", "--version"):
        result = runner.invoke(app, ["--config", str(config), "--data-dir", str(data), flag])
        assert result.exit_code == 0, result.output
        assert not data.exists()


def test_json_error_has_safe_code():
    failure = Failure("source_unavailable", 4)
    assert failure.envelope()["schema_version"] == 1
    assert failure.envelope()["error"]["code"] == "source_unavailable"
    assert "traceback" not in json.dumps(failure.envelope())


def test_catalog_error_is_json_without_traceback(isolated, monkeypatch):
    import sqlite3

    import sessions_manager.catalog as module

    config, data = isolated

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic confidential source path")

    monkeypatch.setattr(module, "Catalog", broken)
    result = runner.invoke(
        app, ["--config", str(config), "--data-dir", str(data), "--format", "json", "list"]
    )
    assert result.exit_code == 6
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "catalog_io_error"
    assert "confidential" not in result.output


def test_json_usage_error_and_internal_failure_are_safe(isolated, monkeypatch):
    import sessions_manager.catalog as module

    config, data = isolated
    base = ["--config", str(config), "--data-dir", str(data), "--format", "json"]
    result = runner.invoke(app, [*base, "list", "--not-a-real-option"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_arguments"

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic confidential source content")

    monkeypatch.setattr(module, "Catalog", broken)
    result = runner.invoke(app, [*base, "list"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "internal_error"
    assert "confidential" not in result.output
