import json

from typer.testing import CliRunner

from sessions_manager.cli import app
from tests.support.claude_factory import make


def test_content_query_and_show_full_ids(isolated, tmp_path):
    config, data = isolated
    root = tmp_path / "native"
    make(root, text="Find this buried needle")
    config.write_text(
        'discovery_roots_mode="replace"\n[[sources]]\nprovider="claude"\npath='
        + repr(str(root))
        + "\n"
    )
    base = ["--config", str(config), "--data-dir", str(data), "--format", "json"]
    result = CliRunner().invoke(app, [*base, "list", "--query", "BURIED"])
    assert result.exit_code == 0, result.output
    row = json.loads(result.stdout)["data"]["items"][0]
    result = CliRunner().invoke(app, [*base, "show", row["display_id"], "--limit", "1"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)["data"]
    assert payload["session"]["native_id"] == "claude-one"
    assert len(payload["events"]) == 1
    assert payload["next_offset"] == 1
    assert payload["usage"]["metrics"]["total_tokens"]["value"] == 20
    human = CliRunner().invoke(app, [*base[:-2], "show", row["display_id"]])
    assert "Capabilities" in human.output and "total_tokens" in human.output


def test_incomplete_content_search_has_partial_exit_and_healthy_filter(isolated, tmp_path):
    import sqlite3

    import tomli_w

    from tests.support.cursor_factory import make as cursor

    config, data = isolated
    claude = tmp_path / "claude"
    make(claude, text="healthy needle")
    other = tmp_path / "cursor"
    chat = cursor(other)
    with sqlite3.connect(chat / "store.db") as db:
        db.execute("DELETE FROM blobs WHERE id='user'")
    db.close()
    config.write_text(
        tomli_w.dumps(
            {
                "discovery_roots_mode": "replace",
                "sources": [
                    {"provider": "claude", "path": str(claude)},
                    {"provider": "cursor", "path": str(other)},
                ],
            }
        )
    )
    base = ["--config", str(config), "--data-dir", str(data), "--format", "json"]
    runner = CliRunner()
    result = runner.invoke(app, [*base, "list", "--query", "healthy"])
    assert result.exit_code == 3, result.output
    assert json.loads(result.stdout)["completeness"]["search"] == "partial"
    result = runner.invoke(app, [*base, "list", "--query", "healthy", "--source", "claude"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["completeness"]["search"] == "complete"
    result = runner.invoke(app, [*base, "stats", "--query", "not present"])
    assert result.exit_code == 3, result.output
    assert json.loads(result.stdout)["completeness"]["search"] == "partial"
