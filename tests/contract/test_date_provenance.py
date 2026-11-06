import json
import sqlite3

import pytest
from typer.testing import CliRunner

from sessions_manager.catalog import Catalog
from sessions_manager.cli import app
from sessions_manager.discovery import adapter
from sessions_manager.models import SourceRoot
from sessions_manager.search import QuerySpec
from sessions_manager.statistics import summarize
from tests.support import claude_factory, codex_factory, cursor_factory, grok_factory


def dated_root(tmp_path, provider, kind):
    raw = {
        "naive": "2026-01-01T12:00:00",
        "aware": "2026-01-01T12:00:00Z",
        "absent": None,
        "invalid": "not-a-date",
        "mixed": "2026-01-01T12:00:00",
    }[kind]
    end = "2026-01-01T13:00:00Z" if kind == "mixed" else raw
    root = SourceRoot.create(provider, tmp_path / provider)
    path = {
        "claude": claude_factory,
        "codex": codex_factory,
        "grok": grok_factory,
        "cursor": cursor_factory,
    }[provider].make(root.path)
    if provider == "claude":
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for index, row in enumerate(rows):
            row["timestamp"] = raw if index == 0 else end
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    elif provider == "codex":
        with sqlite3.connect(root.path / "state_5.sqlite") as db:
            db.execute(
                "UPDATE threads SET created_at=NULL,updated_at=NULL,created_at_ms=?,updated_at_ms=?",
                (raw, end),
            )
    elif provider == "grok":
        file = path / "summary.json"
        row = json.loads(file.read_text())
        row.update(created_at=raw, last_active_at=end)
        file.write_text(json.dumps(row))
    else:
        file = path / "meta.json"
        row = json.loads(file.read_text())
        row.update(createdAtMs=raw, updatedAtMs=end)
        file.write_text(json.dumps(row))
        with sqlite3.connect(path / "store.db") as db:
            meta = json.loads(
                bytes.fromhex(db.execute("SELECT value FROM meta WHERE key='0'").fetchone()[0])
            )
            meta["createdAt"] = raw
            db.execute("UPDATE meta SET value=? WHERE key='0'", (json.dumps(meta).encode().hex(),))
    return root


@pytest.mark.parametrize("provider", ["codex", "claude", "grok", "cursor"])
@pytest.mark.parametrize("kind", ["naive", "aware", "absent", "invalid", "mixed"])
def test_native_date_confidence_preserves_aware_bounds(tmp_path, provider, kind):
    root = dated_root(tmp_path, provider, kind)
    result = adapter(root).discover()
    assert result.complete and len(result.sessions) == 1
    session = result.sessions[0]
    provenance = session.extra["date_provenance"]
    if kind in ("naive", "mixed"):
        assert session.timezone_confidence == "ambiguous"
    elif kind == "aware":
        assert session.timezone_confidence == "known"
    else:
        assert session.timezone_confidence == "unknown"
    if kind in ("aware", "mixed"):
        assert provenance["last_activity_at"]["confidence"] == "known"
        assert QuerySpec(since="2026-01-01", until="2026-01-01").filter([session]) == [session]
    else:
        assert session.last_activity_at is None
        assert not QuerySpec(since="2026-01-01").filter([session])
        assert (
            provenance["last_activity_at"]["reason"]
            == {
                "naive": "timezone_not_recorded",
                "absent": "not_recorded",
                "invalid": "invalid_timestamp",
            }[kind]
        )
    with Catalog(tmp_path / "manager") as catalog:
        catalog.publish(root, [session], complete=True)
        activity = summarize(catalog, [session])["activity_range"]
        assert activity["last_activity_at"] == session.last_activity_at
        if kind == "mixed":
            assert not activity["complete"]


def test_cli_explains_ambiguous_dates_and_keeps_json_reason(isolated, tmp_path):
    config, data = isolated
    root = dated_root(tmp_path, "claude", "naive")
    config.write_text(
        'discovery_roots_mode="replace"\n[[sources]]\nprovider="claude"\npath='
        + repr(str(root.path))
        + "\n"
    )
    base = ["--config", str(config), "--data-dir", str(data)]
    runner = CliRunner()
    result = runner.invoke(app, [*base, "--format", "json", "list"])
    assert result.exit_code == 0, result.output
    row = json.loads(result.stdout)["data"]["items"][0]
    assert row["extra"]["date_provenance"]["created_at"]["reason"] == "timezone_not_recorded"
    human = runner.invoke(app, [*base, "show", row["display_id"]])
    assert human.exit_code == 0, human.output
    assert "ambiguous (timezone not recorded)" in human.output


async def test_tui_details_explain_ambiguous_date(tmp_path):
    from textual.widgets import Static

    from sessions_manager.config import Config
    from sessions_manager.discovery import refresh
    from sessions_manager.ui.app import SessionsApp

    root = dated_root(tmp_path, "claude", "naive")
    cfg = Config(tmp_path / "manager", tmp_path / "config", [root], "replace")
    with Catalog(cfg.data_dir) as catalog:
        refresh(cfg, catalog)
        async with SessionsApp(cfg, catalog).run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert "ambiguous (timezone not recorded)" in " ".join(
                str(s.render()) for s in pilot.app.screen.query(Static)
            )
