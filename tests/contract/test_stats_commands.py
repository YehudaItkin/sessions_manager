import json

from typer.testing import CliRunner

from sessions_manager.cli import app
from tests.support.claude_factory import make


def test_stats_default_hidden_included_and_session_filter(isolated, tmp_path):
    config, data = isolated
    root = tmp_path / "native"
    make(root)
    config.write_text(
        'discovery_roots_mode="replace"\n[[sources]]\nprovider="claude"\npath='
        + repr(str(root))
        + "\n"
    )
    base = ["--config", str(config), "--data-dir", str(data), "--format", "json"]
    runner = CliRunner()
    rows = runner.invoke(app, [*base, "list"])
    uid = json.loads(rows.stdout)["data"]["items"][0]["display_id"]
    runner.invoke(app, [*base, "hide", uid])
    result = runner.invoke(app, [*base, "stats", "--session", uid, "--group-by", "source"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["scope"] == "selected_session_lifetimes"
    assert data["metrics"]["total_tokens"]["value"] == 20
    assert data["metrics"]["messages"]["value"] == 2
    assert data["coverage"]["selected_sessions"] == 1
    assert data["selection"]["scope"] == "all"
    assert data["selection"]["session_ids"] == [uid]
    assert data["activity_range"]["started_at"] == 1767225600000
    assert data["activity_range"]["last_activity_at"] == 1767225601000
