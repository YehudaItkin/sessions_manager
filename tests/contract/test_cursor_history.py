import sqlite3

from sessions_manager.models import SourceRoot
from sessions_manager.sources.cursor import Adapter
from tests.support.cursor_factory import make


def test_binary_hash_references_are_resolved_as_hex_blob_keys(tmp_path):

    from tests.support.cursor_factory import wire

    path = make(tmp_path)
    keys = {name: bytes([i]) * 32 for i, name in enumerate(("turn", "user", "step"), 1)}
    with sqlite3.connect(path / "store.db") as db:
        db.execute("DELETE FROM blobs")
        db.executemany(
            "INSERT INTO blobs VALUES (?,?)",
            [
                ("root", wire(8, keys["turn"])),
                (keys["turn"].hex(), wire(1, wire(1, keys["user"]) + wire(2, keys["step"]))),
                (keys["user"].hex(), wire(1, "Binary reference question")),
                (keys["step"].hex(), wire(1, wire(1, "Binary reference answer"))),
            ],
        )
    db.close()
    reader = Adapter(SourceRoot.create("cursor", tmp_path))
    h = reader.read_history(reader.discover().sessions[0])
    assert h.state == "complete"
    assert [e.text for e in h.events] == ["Binary reference question", "Binary reference answer"]


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


def test_unknown_turn_does_not_hide_later_messages(tmp_path):
    from tests.support.cursor_factory import wire

    path = make(tmp_path)
    with sqlite3.connect(path / "store.db") as db:
        db.execute(
            "UPDATE blobs SET data=? WHERE id='root'", (wire(8, "unknown") + wire(8, "turn"),)
        )
        db.execute("INSERT INTO blobs VALUES (?,?)", ("unknown", wire(99, "unsupported")))
    reader = Adapter(SourceRoot.create("cursor", tmp_path))
    h = reader.read_history(reader.discover().sessions[0])
    assert h.state == "partial"
    assert [e.role for e in h.events] == ["user", "assistant"]


def test_shell_turn_is_read_without_executing_command(tmp_path):
    from tests.support.cursor_factory import wire

    path = make(tmp_path)
    with sqlite3.connect(path / "store.db") as db:
        db.execute(
            "UPDATE blobs SET data=? WHERE id='root'", (wire(8, "shell-turn") + wire(8, "turn"),)
        )
        db.executemany(
            "INSERT INTO blobs VALUES (?,?)",
            [
                ("shell-turn", wire(2, wire(1, "command") + wire(2, "output"))),
                ("command", wire(1, "echo SYNTHETIC-COMMAND")),
                ("output", wire(1, "SYNTHETIC-OUTPUT") + wire(2, "SYNTHETIC-STDERR")),
            ],
        )
    reader = Adapter(SourceRoot.create("cursor", tmp_path))
    h = reader.read_history(reader.discover().sessions[0])
    assert h.state == "complete"
    assert [e.role for e in h.events] == ["tool_call", "tool_result", "user", "assistant"]
    assert h.events[1].text == "SYNTHETIC-OUTPUT\nSYNTHETIC-STDERR"


def test_legacy_text_reference_of_hash_length_remains_readable(tmp_path):
    from tests.support.cursor_factory import wire

    path = make(tmp_path)
    key = "a" * 32
    with sqlite3.connect(path / "store.db") as db:
        db.execute("UPDATE blobs SET data=? WHERE id='root'", (wire(8, key),))
        db.execute("UPDATE blobs SET id=? WHERE id='turn'", (key,))
    reader = Adapter(SourceRoot.create("cursor", tmp_path))
    history = reader.read_history(reader.discover().sessions[0])
    assert history.state == "complete"
    assert [e.role for e in history.events] == ["user", "assistant"]
