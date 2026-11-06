import json

import pytest
import tomli_w
from textual.widgets import Static
from typer.testing import CliRunner

from sessions_manager.catalog import Catalog
from sessions_manager.cli import app as cli
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.ui.app import SessionsApp


@pytest.mark.parametrize("provider", ["cursor", "grok"])
async def test_cli_and_tui_expose_only_verified_alias_content(tmp_path, provider):
    if provider == "cursor":
        from tests.integration.test_cursor_alias_locations import copies

        root, _, _ = copies(tmp_path, "text")
    else:
        from tests.integration.test_alias_usage import change_usage, usage_copies

        roots, _, second = usage_copies(tmp_path, "grok", True)
        root = roots[0]
        change_usage(second, "grok", "conflict")
    cfg = Config(tmp_path / "manager", tmp_path / "config.toml", [root], "replace")
    cfg.prepare()
    cfg.config_path.write_text(
        tomli_w.dumps(
            {
                "discovery_roots_mode": "replace",
                "sources": [{"provider": provider, "path": str(root.path)}],
            }
        )
    )
    with Catalog(cfg.data_dir) as catalog:
        refresh(cfg, catalog)
        session = catalog.sessions()[0]
        base = [
            "--config",
            str(cfg.config_path),
            "--data-dir",
            str(cfg.data_dir),
            "--format",
            "json",
        ]
        runner = CliRunner()
        shown = runner.invoke(cli, [*base, "show", session.display_id])
        assert shown.exit_code == 0, shown.output
        data = json.loads(shown.stdout)["data"]
        assert bool(data["events"]) == (provider == "grok")
        assert data["usage"]["metrics"]["total_tokens"]["value"] is None
        stats = runner.invoke(cli, [*base, "stats", "--session", session.display_id])
        assert stats.exit_code == 0, stats.output
        assert json.loads(stats.stdout)["data"]["metrics"]["total_tokens"]["value"] is None
        app = SessionsApp(cfg, catalog)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("enter")
            text = " ".join(str(w.render()) for w in app.screen.query(Static))
            if provider == "cursor":
                assert "ALPHA" not in text and "BETA" not in text
            else:
                assert "Synthetic Grok question" in text
                assert "Copies of this session contain different usage evidence" in text
            assert "999" not in text
