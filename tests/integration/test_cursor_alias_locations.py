import pickle
import shutil
import sqlite3

import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import (
    prepare_scan,
    publish_scan,
    scan_for_transport,
    scan_metadata,
    scan_root,
)
from sessions_manager.models import SourceRoot
from sessions_manager.sources.cursor import Adapter
from tests.support.cursor_factory import make, wire


def copies(tmp_path, variant):
    root = SourceRoot.create("cursor", tmp_path / "native")
    first = make(root.path, "same", cwd=tmp_path / "project", text="ALPHA synthetic")
    second = root.path / "chats" / "second-workspace" / first.name
    shutil.copytree(first, second)
    with sqlite3.connect(second / "store.db") as db:
        if variant == "text":
            db.execute("UPDATE blobs SET data=? WHERE id='user'", (wire(1, "BETA synthetic"),))
        elif variant == "graph":
            db.execute(
                "UPDATE blobs SET data=? WHERE id='turn'",
                (wire(1, wire(1, "other-user") + wire(2, "step")),),
            )
            db.execute("INSERT INTO blobs VALUES ('other-user',?)", (wire(1, "ALPHA synthetic"),))
    return root, first, second


@pytest.mark.parametrize("reverse", [False, True])
def test_cursor_reader_keeps_each_physical_history(tmp_path, monkeypatch, reverse):
    root, first, second = copies(tmp_path, "text")
    if reverse:
        monkeypatch.setattr(
            "sessions_manager.sources.cursor.read_many",
            lambda reader, paths: [reader(p) for p in reversed(paths)],
        )
    reader = Adapter(root)
    result = reader.discover()
    by_path = {s.locator: s for s in result.sessions}
    assert reader.read_history(by_path[str(first)]).events[0].text == "ALPHA synthetic"
    assert reader.read_history(by_path[str(second)]).events[0].text == "BETA synthetic"


@pytest.mark.parametrize("variant", ["same", "text", "graph"])
@pytest.mark.parametrize("transport", [False, True])
def test_cursor_alias_metadata_full_warm_and_disappearance(tmp_path, variant, transport):
    root, first, second = copies(tmp_path, variant)
    original = {
        p: p.read_bytes() for base in (first, second) for p in base.iterdir() if p.is_file()
    }
    cfg = Config(tmp_path / "manager", tmp_path / "config", [root], "replace")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        for cycle in range(2):
            _, args = prepare_scan(cfg, catalog)
            publish_scan(catalog, root, scan_metadata(args[0]))
            result = (scan_for_transport if transport else scan_root)(args[0])
            if transport:
                result = pickle.loads(pickle.dumps(result))
            publish_scan(catalog, root, result)
            assert len(catalog.sessions()) == 1
            session = catalog.sessions()[0]
            if cycle == 0:
                uid = session.session_uid
                catalog.hide([uid], True)
            assert session.session_uid == uid
            if variant == "same":
                assert session.history_state == "complete"
                assert catalog.events(uid)[0]["text"] == "ALPHA synthetic"
                assert len(session.extra["alias_bindings"]) == 2
            else:
                assert session.extra.get("identity_conflict") == "identity_conflict"
                assert not catalog.events(uid)
                assert not catalog.matching_ids("ALPHA") and not catalog.matching_ids("BETA")
                assert session.capabilities["resume"].state != "supported"
        assert all(p.read_bytes() == raw for p, raw in original.items())
        shutil.rmtree(second)
        _, args = prepare_scan(cfg, catalog)
        publish_scan(catalog, root, scan_root(args[0]))
        session = catalog.get(uid)
        assert session.hidden and session.history_state == "complete"
        assert not session.extra.get("identity_conflict")
        assert catalog.events(uid)[0]["text"] == "ALPHA synthetic"


async def test_tui_rebuilds_invalidated_history_cache_without_losing_ids(tmp_path):
    from sessions_manager.discovery import refresh
    from sessions_manager.ui.app import SessionsApp

    root, _, _ = copies(tmp_path, "same")
    cfg = Config(tmp_path / "manager", tmp_path / "config", [root], "replace")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        refresh(cfg, catalog)
        uid = catalog.sessions()[0].session_uid
        catalog.hide([uid], True)
        with catalog.writer() as db:
            db.execute("UPDATE index_meta SET value='previous-normalizer' WHERE key='normalizer'")
    with Catalog(cfg.data_dir) as catalog:
        assert not catalog.index_valid
        app = SessionsApp(cfg, catalog)
        async with app.run_test(size=(80, 24)) as pilot:
            for _ in range(40):
                await pilot.pause(0.05)
                if catalog.get(uid).search_state == "complete":
                    break
            assert catalog.matching_ids("ALPHA synthetic") == {uid}
            assert catalog.get(uid).hidden and len(catalog.sessions()) == 1
