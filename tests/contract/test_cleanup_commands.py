import json

from typer.testing import CliRunner

from sessions_manager.cli import app
from tests.support.claude_factory import make


def test_cleanup_preview_confirm_restore_and_purge(isolated, tmp_path):
    config, data = isolated
    root = tmp_path / "native"
    path = make(root)
    config.write_text(
        'discovery_roots_mode="replace"\n[[sources]]\nprovider="claude"\nexecutable_version="synthetic"\npath='
        + repr(str(root))
        + "\n"
    )
    base = ["--config", str(config), "--data-dir", str(data), "--format", "json"]
    runner = CliRunner()
    rows = runner.invoke(app, [*base, "list"])
    uid = json.loads(rows.stdout)["data"]["items"][0]["display_id"]
    hidden = runner.invoke(app, [*base, "hide", uid])
    assert hidden.exit_code == 0, hidden.output
    plan = runner.invoke(app, [*base, "delete", uid])
    assert plan.exit_code == 0, plan.output
    token = json.loads(plan.stdout)["data"]["confirmation_token"]
    assert path.exists()
    result = runner.invoke(app, [*base, "delete", uid, "--confirm", token, "--assert-closed"])
    assert result.exit_code == 0, result.output
    trash = json.loads(result.stdout)["data"]["items"][0]["trash_id"]
    restore = runner.invoke(app, [*base, "trash", "restore", trash])
    assert restore.exit_code == 0, restore.output
    token = json.loads(restore.stdout)["data"]["confirmation_token"]
    result = runner.invoke(app, [*base, "trash", "restore", trash, "--confirm", token])
    assert result.exit_code == 0, result.output
    assert path.exists()
