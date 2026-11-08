import sqlite3

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.models import SourceRoot
from sessions_manager.sources.sqlite_reader import NativeSQLite
from tests.support.cursor_factory import make, wire


def test_cursor_commit_during_graph_read_is_coherent_and_next_refresh_rebuilds(
    tmp_path, monkeypatch
):
    root = SourceRoot.create("cursor", tmp_path / "native")
    path = make(root.path, text="before-question")
    writer = sqlite3.connect(path / "store.db", check_same_thread=False)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("UPDATE blobs SET data=? WHERE id='step'", (wire(1, wire(1, "before-answer")),))
    writer.commit()
    cfg = Config(tmp_path / "manager", tmp_path / "unused.toml", [root], "replace")
    cfg.prepare()
    read = NativeSQLite.read
    changed = False

    def commit_after_question(reader, table, columns, **kwargs):
        nonlocal changed
        rows = read(reader, table, columns, **kwargs)
        if table == "blobs" and kwargs.get("value") == "user" and not changed:
            changed = True
            writer.execute("UPDATE blobs SET data=? WHERE id='user'", (wire(1, "after-question"),))
            writer.execute(
                "UPDATE blobs SET data=? WHERE id='step'", (wire(1, wire(1, "after-answer")),)
            )
            writer.commit()
        return rows

    monkeypatch.setattr(NativeSQLite, "read", commit_after_question)
    try:
        with Catalog(cfg.data_dir) as catalog:
            refresh(cfg, catalog)
            session = catalog.sessions()[0]
            assert changed
            assert [e["text"] for e in catalog.events(session.session_uid)] == [
                "before-question",
                "before-answer",
            ]
            assert session.history_state == "complete"
            refresh(cfg, catalog)
            session = catalog.get(session.session_uid)
            assert [e["text"] for e in catalog.events(session.session_uid)] == [
                "after-question",
                "after-answer",
            ]
            assert catalog.matching_ids("after-question") == {session.session_uid}
            assert not catalog.matching_ids("before-question")
    finally:
        writer.close()
