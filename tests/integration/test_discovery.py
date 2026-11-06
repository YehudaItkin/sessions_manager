import json
from pathlib import Path

import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.models import SourceRoot
from tests.support.claude_factory import make


@pytest.mark.parametrize("provider", ["codex", "claude", "grok", "cursor"])
def test_fresh_missing_root_is_unavailable_not_complete_empty(tmp_path, provider):
    from sessions_manager.discovery import adapter, scan_root

    root = SourceRoot.create(provider, tmp_path / "missing")
    for result in (adapter(root).discover(), scan_root((root, {}))):
        assert not result.complete
        assert result.reason == "source_unavailable"


def test_denied_child_enumeration_preserves_cached_sessions(isolated, tmp_path, monkeypatch):
    import os

    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    make(root.path)
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    original = os.scandir
    target = (root.path / "projects").stat()

    def denied(path):
        info = os.fstat(path) if isinstance(path, int) else Path(path).stat()
        if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
            raise PermissionError("synthetic denied listing")
        return original(path)

    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        uid = catalog.sessions()[0].session_uid
        monkeypatch.setattr(os, "scandir", denied)
        receipts = refresh(cfg, catalog)
        assert receipts[0]["state"] == "partial"
        assert catalog.get(uid).presence != "missing"
        assert len(catalog.events(uid)) == 2


def test_deep_content_keeps_healthy_neighbor_and_metadata(isolated, tmp_path):
    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    path = make(root.path, "broken")
    make(root.path, "healthy", message_id="healthy-api")
    path.write_text(
        path.read_text().replace(
            '"Synthetic Claude question"', "[" * 1100 + '"nested"' + "]" * 1100
        )
    )
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        receipts = refresh(cfg, catalog)
        assert receipts[0]["state"] == "partial"
        sessions = {s.native_id: s for s in catalog.sessions()}
        assert set(sessions) == {"broken", "healthy"}
        assert sessions["healthy"].history_state == "complete"
        assert sessions["broken"].history_state != "complete"


def test_unexpected_worker_failure_is_isolated_and_interrupt_is_not_swallowed(
    tmp_path, monkeypatch
):
    from sessions_manager.discovery import collect_scan
    from sessions_manager.sources.claude import Adapter

    root = SourceRoot.create("claude", tmp_path)

    def broken(self):
        raise RuntimeError("synthetic private content must not be diagnostic")

    monkeypatch.setattr(Adapter, "discover", broken)
    result = collect_scan([(root, {})])[0]
    assert not result.complete and result.reason == "source_reader_failed"

    def interrupted(self):
        raise KeyboardInterrupt()

    monkeypatch.setattr(Adapter, "discover", interrupted)
    with pytest.raises(KeyboardInterrupt):
        collect_scan([(root, {})])


@pytest.mark.parametrize("provider", ["claude", "grok"])
def test_bad_optional_preview_or_record_never_discards_healthy_neighbors(
    isolated, tmp_path, provider
):
    from tests.support import grok_factory

    config, data = isolated
    root = SourceRoot.create(provider, tmp_path / "native")
    factory = make if provider == "claude" else grok_factory.make
    broken = factory(root.path, "broken")
    factory(root.path, "healthy", **({"message_id": "other"} if provider == "claude" else {}))
    if provider == "claude":
        records = [json.loads(line) for line in broken.read_text().splitlines()]
        records[0]["message"]["content"] = [123]
        broken.write_text("".join(json.dumps(r) + "\n" for r in records))
    else:
        (broken / "summary.json").write_text(json.dumps({"info": []}))
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        sessions = {s.native_id: s for s in catalog.sessions()}
        assert "healthy" in sessions
        assert sessions["healthy"].history_state == "complete"
        if provider == "claude":
            assert "broken" in sessions
            assert sessions["broken"].preview is None
            assert sessions["broken"].history_state == "partial"
        else:
            assert catalog.root_states()[0]["state"] != "complete"


def test_metadata_is_published_before_optional_history_and_has_generation_provenance(
    isolated, tmp_path, monkeypatch
):
    import threading

    from sessions_manager.sources.claude import Adapter

    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    make(root.path)
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    metadata_published = threading.Event()
    original_history = Adapter.read_history
    original_publish = Catalog.publish

    def checked_history(self, session):
        assert metadata_published.is_set(), "history began before early metadata publication"
        return original_history(self, session)

    def observed_publish(self, root, sessions, **kwargs):
        result = original_publish(self, root, sessions, **kwargs)
        if sessions and not kwargs.get("histories"):
            assert self.sessions()[0].search_state != "complete"
            metadata_published.set()
        return result

    monkeypatch.setattr(Adapter, "read_history", checked_history)
    monkeypatch.setattr(Catalog, "publish", observed_publish)
    with Catalog(data) as catalog:
        assert refresh(cfg, catalog)[0]["state"] == "complete"
        assert metadata_published.is_set()
        rows = catalog.connection.execute(
            "SELECT payload FROM generations ORDER BY rowid"
        ).fetchall()
        assert len(rows) == 2
        early, final = [json.loads(row[0]) for row in rows]
        assert early["history"] == "partial"
        assert final["started_at"] <= final["finished_at"]
        assert final["history"] == "complete"
        assert final["source_revision_range"]


def test_jsonl_append_cursor_reuses_confirmed_prefix_and_rebuilds_changed_prefix(
    isolated, tmp_path
):
    from tests.support.claude_factory import append

    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    path = make(root.path)
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        old_size = path.stat().st_size
    append(
        path,
        {
            "type": "user",
            "uuid": "tail",
            "sessionId": "claude-one",
            "message": {"content": "new tail needle"},
            "credential": "must-not-cache",
        },
    )
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        cursor = json.loads(
            __import__("zlib").decompress(
                catalog.connection.execute("SELECT payload FROM jsonl_cursors").fetchone()[0]
            )
        )
        assert cursor["audit"]["mode"] == "append_tail"
        assert cursor["audit"]["validated_prefix_bytes"] == old_size
        assert cursor["audit"]["decoded_tail_bytes"] == path.stat().st_size - old_size
        assert "must-not-cache" not in json.dumps(cursor)
        assert len(catalog.events(catalog.sessions()[0].session_uid)) == 3
        # In-place prefix modification plus growth must never be mistaken for append.
        path.write_text(
            path.read_text().replace("Synthetic Claude question", "changed prefix needle")
        )
        refresh(cfg, catalog)
        cursor = json.loads(
            __import__("zlib").decompress(
                catalog.connection.execute("SELECT payload FROM jsonl_cursors").fetchone()[0]
            )
        )
        assert cursor["audit"]["mode"] == "full"
        assert catalog.matching_ids("changed prefix needle")
        assert not catalog.matching_ids("Synthetic Claude question")


def test_one_usage_failure_keeps_every_session_and_cached_history(isolated, tmp_path, monkeypatch):
    from sessions_manager.sources.claude import Adapter

    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    path = make(root.path, "one")
    make(root.path, "two", message_id="other-answer")
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        uid = next(s.session_uid for s in catalog.sessions() if s.native_id == "one")
        before = catalog.events(uid)
        path.write_text(path.read_text() + "\n")

        def broken(self, session):
            if session.native_id == "one":
                raise AttributeError("synthetic private payload")
            return original(self, session)

        original = Adapter.read_usage
        monkeypatch.setattr(Adapter, "read_usage", broken)
        refresh(cfg, catalog)
        assert {s.native_id for s in catalog.sessions()} == {"one", "two"}
        assert catalog.get(uid).usage_state == "partial"
        assert catalog.get(uid).history_state == "complete"
        assert catalog.events(uid) == before
        monkeypatch.setattr(Adapter, "read_usage", original)
        refresh(cfg, catalog)
        assert catalog.get(uid).usage_state == "complete"


def test_history_failure_preserves_metadata_and_previous_events(isolated, tmp_path, monkeypatch):
    from sessions_manager.sources.claude import Adapter

    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    path = make(root.path)
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        uid = catalog.sessions()[0].session_uid
        before = catalog.events(uid)
        path.write_text(path.read_text() + "\n")

        def broken(self, session):
            raise TypeError("synthetic private payload")

        monkeypatch.setattr(Adapter, "read_history", broken)
        refresh(cfg, catalog)
        assert catalog.get(uid).history_state == "partial"
        assert catalog.get(uid).presence == "present"
        assert catalog.events(uid) == before


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
        latest = json.loads(
            catalog.connection.execute(
                "SELECT payload FROM generations ORDER BY rowid DESC LIMIT 1"
            ).fetchone()[0]
        )
        assert latest["history"] != "complete"
        assert latest["search"] != "complete"
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
