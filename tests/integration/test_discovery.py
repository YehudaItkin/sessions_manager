from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.models import SourceRoot
from tests.support.claude_factory import make


def test_selected_provider_refresh_not_display_filter(isolated, tmp_path):
    path, data = isolated
    a = SourceRoot.create("claude", tmp_path / "claude")
    c = SourceRoot.create("claude", tmp_path / "other", namespace="other")
    make(a.path, "A", cwd=tmp_path / "project A")
    bfile = make(a.path, "B", cwd=tmp_path / "project B")
    make(c.path, "C")
    cfg = Config(data, path, [a, c], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        old = catalog.get(
            next(s.display_id for s in catalog.sessions() if s.native_id == "C")
        ).current_generation
        bfile.write_text(bfile.read_text().replace("Synthetic Claude question", "Changed B"))
        c.enabled = False
        refresh(cfg, catalog, providers=["claude"])
        b = next(s for s in catalog.sessions() if s.native_id == "B")
        assert b.presence == "present"
        assert "Changed B" in b.preview
        assert next(s for s in catalog.sessions() if s.native_id == "C").current_generation == old


def test_cancel_and_missing_previously_available_root_retains_history(isolated, tmp_path):
    import shutil
    import threading

    path, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    make(root.path)
    cfg = Config(data, path, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        uid = catalog.sessions()[0].session_uid
        old_events = catalog.events(uid)
        cancelled = threading.Event()
        cancelled.set()
        result = refresh(cfg, catalog, cancel=cancelled)
        assert result[0]["state"] == "partial"
        assert catalog.events(uid) == old_events
        shutil.rmtree(root.path)
        result = refresh(cfg, catalog)
        assert result[0]["state"] == "partial"
        assert catalog.get(uid).presence != "missing"
        assert catalog.events(uid) == old_events


def test_cleanup_capability_matches_proven_profile(isolated, tmp_path):
    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native", executable_version="synthetic")
    make(root.path)
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        assert catalog.sessions()[0].capabilities["cleanup"].state == "supported"
        root.executable_version = "future-version"
        refresh(cfg, catalog)
        capability = catalog.sessions()[0].capabilities["cleanup"]
        assert capability.state == "unavailable"
        assert capability.reason == "cleanup_profile_unverified"


def test_incompatible_copies_disable_actions_and_ambiguous_history(isolated, tmp_path):
    config, data = isolated
    a = SourceRoot.create("claude", tmp_path / "a")
    b = SourceRoot.create("claude", tmp_path / "b")
    make(a.path, "same", cwd=tmp_path / "project")
    other = make(b.path, "same", cwd=tmp_path / "project")
    other.write_text(other.read_text().replace("Synthetic answer", "incompatible answer"))
    cfg = Config(data, config, [a, b], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        assert len(catalog.sessions()) == 1
        session = catalog.sessions()[0]
        assert session.capabilities["resume"].state == "unsafe"
        assert session.capabilities["cleanup"].reason == "identity_conflict"
        assert session.history_state == "unavailable"
        assert catalog.events(session.session_uid) == []


def test_codex_projection_wal_append_invalidates_cached_history(isolated, tmp_path):
    import json
    import sqlite3

    from tests.support.codex_factory import make as codex

    config, data = isolated
    root = SourceRoot.create("codex", tmp_path / "native")
    codex(root.path)
    writer = sqlite3.connect(root.path / "thread_history_1.sqlite")
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("UPDATE thread_items SET updated_at_ordinal=2")
    writer.commit()
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    try:
        with Catalog(data) as catalog:
            refresh(cfg, catalog)
            uid = catalog.sessions()[0].session_uid
            assert catalog.events(uid)[0]["text"] == "Synthetic Codex question"
            writer.execute(
                "UPDATE thread_items SET item_json=?",
                (
                    json.dumps(
                        {
                            "type": "userMessage",
                            "id": "item-codex-one",
                            "content": [{"type": "inputText", "text": "new WAL content"}],
                        }
                    ),
                ),
            )
            writer.commit()
            refresh(cfg, catalog)
            assert catalog.events(uid)[0]["text"] == "new WAL content"
    finally:
        writer.close()


def test_search_normalizer_change_rebuilds_before_cli_claims_complete(isolated, tmp_path):
    import json

    from typer.testing import CliRunner

    from sessions_manager.cli import app

    config, data = isolated
    root = tmp_path / "native"
    make(root, text="normalizer needle")
    config.write_text(
        'discovery_roots_mode="replace"\n[[sources]]\nprovider="claude"\npath='
        + repr(str(root))
        + "\n"
    )
    args = ["--config", str(config), "--data-dir", str(data), "--format", "json"]
    runner = CliRunner()
    assert runner.invoke(app, [*args, "list"]).exit_code == 0
    with Catalog(data) as catalog:
        catalog.connection.execute(
            "UPDATE index_meta SET value='old-unicode' WHERE key='normalizer'"
        )
        catalog.connection.commit()
    result = runner.invoke(app, [*args, "list", "--query", "normalizer"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["total"] == 1
    assert json.loads(result.stdout)["completeness"]["search"] == "complete"
