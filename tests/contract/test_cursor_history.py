import sqlite3

from sessions_manager.models import SourceRoot
from sessions_manager.sources.cursor import Adapter
from tests.support.cursor_factory import make


def test_reachable_order_and_orphans_excluded(tmp_path):
    make(tmp_path)
    adapter = Adapter(SourceRoot.create("cursor", tmp_path))
    history = adapter.read_history(adapter.discover().sessions[0])
    assert history.state == "complete"
    assert [e.role for e in history.events] == ["user", "assistant"]
    assert all("orphan" not in (e.text or "") for e in history.events)


def test_missing_reference_is_partial(tmp_path):
    path = make(tmp_path)
    with sqlite3.connect(path / "store.db") as db:
        db.execute("DELETE FROM blobs WHERE id='user'")
    adapter = Adapter(SourceRoot.create("cursor", tmp_path))
    assert adapter.read_history(adapter.discover().sessions[0]).state == "partial"
