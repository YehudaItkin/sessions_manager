from sessions_manager.catalog import Catalog
from sessions_manager.config import ensure_private
from sessions_manager.models import HistoryEvent, HistoryResult, Session, SourceRoot


def test_replace_removes_stale_index_and_deduplicates(tmp_path):
    ensure_private(tmp_path / "data")
    root = SourceRoot.create("claude", tmp_path / "native")
    session = Session.build(root, "one", root.path / "one")
    with Catalog(tmp_path / "data") as catalog:
        catalog.publish(root, [session], complete=True)
        catalog.replace_history(
            session, HistoryResult([HistoryEvent("one", "user", 0, text="old needle")])
        )
        assert len(catalog.events(session.session_uid)) == 1
        catalog.replace_history(
            session, HistoryResult([HistoryEvent("two", "assistant", 1, text="new text")])
        )
        assert [e["text"] for e in catalog.events(session.session_uid)] == ["new text"]
        assert catalog.matching_ids("needle") == set()


def test_compressed_history_retains_exact_text_and_search(tmp_path):

    ensure_private(tmp_path / "data")
    root = SourceRoot.create("claude", tmp_path / "native")
    session = Session.build(root, "one", root.path / "one")
    text = "synthetic " * 20000 + "🧪 boundary needle"
    with Catalog(tmp_path / "data") as catalog:
        catalog.publish(root, [session], complete=True)
        catalog.replace_history(
            session, HistoryResult([HistoryEvent("large", "user", 0, text=text)])
        )
        assert catalog.events(session.session_uid)[0]["text"] == text
        assert catalog.matching_ids("boundary needle") == {session.session_uid}
        stored = catalog.connection.execute("SELECT payload FROM events").fetchone()[0]
        assert isinstance(stored, bytes)
        assert len(stored) < len(text) // 10


def test_shared_event_keeps_each_session_order_and_branch(tmp_path):
    ensure_private(tmp_path / "data")
    root = SourceRoot.create("claude", tmp_path / "native")
    one = Session.build(root, "one", root.path / "one")
    two = Session.build(root, "two", root.path / "two")
    with Catalog(tmp_path / "data") as catalog:
        catalog.publish(root, [one, two], complete=True)
        catalog.replace_history(
            one,
            HistoryResult(
                [HistoryEvent("shared", "assistant", 1, text="shared", parent_id="branch-one")]
            ),
        )
        catalog.replace_history(
            two,
            HistoryResult(
                [HistoryEvent("shared", "assistant", 8, text="shared", parent_id="branch-two")]
            ),
        )
        assert catalog.events(one.session_uid)[0]["ordinal"] == 1
        assert catalog.events(one.session_uid)[0]["parent_id"] == "branch-one"
        assert catalog.events(two.session_uid)[0]["ordinal"] == 8
        assert catalog.events(two.session_uid)[0]["parent_id"] == "branch-two"


def test_conflicting_shared_revision_preserves_each_history_and_search(tmp_path):
    root = SourceRoot.create("claude", tmp_path / "native")
    one = Session.build(root, "one", root.path / "one")
    two = Session.build(root, "two", root.path / "two")
    with Catalog(tmp_path / "data") as catalog:
        catalog.publish(root, [one, two], complete=True)
        old = HistoryResult([HistoryEvent("shared", "assistant", 1, text="ALPHA snapshot")])
        new = HistoryResult([HistoryEvent("shared", "assistant", 8, text="BETA snapshot")])
        catalog.replace_history(one, old)
        catalog.replace_history(two, new)
        assert catalog.events(one.session_uid)[0]["text"] == "ALPHA snapshot"
        assert catalog.events(two.session_uid)[0]["text"] == "BETA snapshot"
        assert catalog.matching_ids("ALPHA") == {one.session_uid}
        assert catalog.matching_ids("BETA") == {two.session_uid}
        assert catalog.get(one.display_id).history_state == "partial"
        assert catalog.get(two.display_id).history_state == "partial"
        from sessions_manager.statistics import summarize

        assert summarize(catalog, catalog.sessions())["metrics"]["messages"]["value"] == 1
        catalog.replace_history(two, new)
        assert len(catalog.events(two.session_uid)) == 1
        # A freshly read complete revision can converge without changing its neighbor.
        catalog.replace_history(one, new)
        assert catalog.matching_ids("ALPHA") == set()
        assert catalog.matching_ids("BETA") == {one.session_uid, two.session_uid}


def test_worker_transport_keeps_conflicting_shared_bodies_separate(tmp_path):
    from sessions_manager.discovery import publish_scan, scan_for_transport
    from tests.support.claude_factory import make

    root = SourceRoot.create("claude", tmp_path / "native")
    for native, text in (("one", "ALPHA revision"), ("two", "BETA revision")):
        path = make(root.path, native)
        path.write_text(path.read_text().replace("Synthetic answer", text))
    scanned = scan_for_transport((root, {}))
    with Catalog(tmp_path / "data") as catalog:
        publish_scan(catalog, root, scanned)
        for session in catalog.sessions():
            expected = "ALPHA revision" if session.native_id == "one" else "BETA revision"
            assert catalog.events(session.session_uid)[1]["text"] == expected
            assert catalog.matching_ids(expected) == {session.session_uid}
