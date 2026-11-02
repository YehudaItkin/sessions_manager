from sessions_manager.models import SourceRoot
from sessions_manager.sources.codex import Adapter
from tests.support.codex_factory import make


def test_projection_survives_rollout_and_deduplicates(tmp_path):
    make(tmp_path, rollout=False)
    adapter = Adapter(SourceRoot.create("codex", tmp_path))
    session = adapter.discover().sessions[0]
    history = adapter.read_history(session)
    assert history.state == "complete"
    assert [e.text for e in history.events] == ["Synthetic Codex question"]


def test_unknown_item_partial(tmp_path):
    import json
    import sqlite3

    make(tmp_path)
    with sqlite3.connect(tmp_path / "thread_history_1.sqlite") as db:
        db.execute(
            "UPDATE thread_items SET item_json=?", (json.dumps({"type": "futureKind", "id": "x"}),)
        )
    adapter = Adapter(SourceRoot.create("codex", tmp_path))
    assert adapter.read_history(adapter.discover().sessions[0]).state == "partial"


def test_realtime_projection_is_displayed_once(tmp_path):
    import json
    import sqlite3

    make(tmp_path)
    with sqlite3.connect(tmp_path / "thread_history_1.sqlite") as db:
        db.execute(
            "INSERT INTO thread_realtime_items VALUES (?,?,?,?,?,?)",
            (
                "codex-one",
                "realtime-answer",
                2,
                1767225601123,
                "agentMessage",
                json.dumps({"type": "agentMessage", "text": "Realtime answer"}),
            ),
        )
    db.close()
    reader = Adapter(SourceRoot.create("codex", tmp_path))
    history = reader.read_history(reader.discover().sessions[0])
    assert history.state == "complete"
    assert [event.text for event in history.events] == [
        "Synthetic Codex question",
        "Realtime answer",
    ]


def test_projection_changed_after_metadata_is_partial(tmp_path):
    import json
    import sqlite3

    make(tmp_path)
    reader = Adapter(SourceRoot.create("codex", tmp_path))
    session = reader.discover().sessions[0]
    with sqlite3.connect(tmp_path / "thread_history_1.sqlite") as db:
        db.execute(
            "UPDATE thread_items SET item_json=?",
            (json.dumps({"type": "agentMessage", "text": "changed"}),),
        )
    db.close()
    assert reader.read_history(session).state == "partial"
