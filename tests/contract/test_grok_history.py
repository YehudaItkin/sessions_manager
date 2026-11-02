from sessions_manager.models import SourceRoot
from sessions_manager.sources.grok import Adapter
from tests.support.grok_factory import make


def test_acp_and_truncated_tail_preserves_prefix(tmp_path):
    path = make(tmp_path)
    with (path / "updates.jsonl").open("a") as stream:
        stream.write('{"unfinished":')
    adapter = Adapter(SourceRoot.create("grok", tmp_path))
    history = adapter.read_history(adapter.discover().sessions[0])
    assert history.state == "partial"
    assert [e.role for e in history.events] == ["user", "assistant"]
    assert history.events[0].text == "Synthetic Grok question"


def test_prompt_chunks_use_prompt_identity_not_unique_event_ids(tmp_path):
    import json

    path = make(tmp_path)
    rows = [json.loads(line) for line in (path / "updates.jsonl").read_text().splitlines()]
    rows[1]["params"]["update"].pop("_meta", None)
    rows[1]["params"]["_meta"] = {"eventId": "event-one", "promptId": "prompt-one"}
    extra = json.loads(json.dumps(rows[1]))
    extra["params"]["_meta"]["eventId"] = "event-two"
    extra["params"]["update"]["content"]["text"] = " continued"
    (path / "updates.jsonl").write_text("".join(json.dumps(row) + "\n" for row in [*rows, extra]))
    reader = Adapter(SourceRoot.create("grok", tmp_path))
    history = reader.read_history(reader.discover().sessions[0])
    assert history.state == "complete"
    assert [event.role for event in history.events] == ["user", "assistant"]
    assert history.events[1].text == "Synthetic answer continued"


def test_raw_history_is_an_alternative_not_a_duplicate(tmp_path):
    import json

    path = make(tmp_path)
    (path / "updates.jsonl").unlink()
    rows = [
        {"type": "system", "content": "internal context excluded"},
        {"type": "user", "content": [{"type": "text", "text": "Raw question"}]},
        {"type": "assistant", "content": "Raw answer"},
    ]
    (path / "chat_history.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    reader = Adapter(SourceRoot.create("grok", tmp_path))
    history = reader.read_history(reader.discover().sessions[0])
    assert history.state == "complete"
    assert [event.text for event in history.events] == ["Raw question", "Raw answer"]
