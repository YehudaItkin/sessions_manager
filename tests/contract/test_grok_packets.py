import copy
import json

import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.models import SourceRoot
from sessions_manager.sources.grok import Adapter
from sessions_manager.statistics import summarize
from tests.support.grok_factory import make


@pytest.mark.parametrize("kind", ["adjacent", "separated", "conflict", "legitimate", "tool"])
def test_packet_identity_controls_replay_without_losing_real_chunks(tmp_path, kind):
    path = make(tmp_path / "native")
    source = path / "updates.jsonl"
    user, answer = [json.loads(line) for line in source.read_text().splitlines()]
    user["params"]["update"]["messageId"] = "user-message"
    duplicate = copy.deepcopy(user)
    if kind == "conflict":
        duplicate["params"]["update"]["content"]["text"] = "CONFLICTING PACKET"
    if kind == "legitimate":
        duplicate["params"]["update"]["_meta"]["eventId"] = "other-packet"
    rows = [user, answer, duplicate] if kind == "separated" else [user, duplicate, answer]
    if kind == "tool":
        call = {
            "params": {
                "sessionId": "grok-one",
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "tool",
                    "title": "Synthetic action",
                    "status": "in_progress",
                    "_meta": {"eventId": "tool-start"},
                },
            }
        }
        done = copy.deepcopy(call)
        done["params"]["update"].update(
            sessionUpdate="tool_call_update",
            status="completed",
            content=[{"content": {"type": "text", "text": "Synthetic output"}}],
            _meta={"eventId": "tool-done"},
        )
        rows = [user, call, done, copy.deepcopy(done), copy.deepcopy(call), answer]
    source.write_text("".join(json.dumps(row) + "\n" for row in rows))
    root = SourceRoot.create("grok", tmp_path / "native")
    reader = Adapter(root)
    history = reader.read_history(reader.discover().sessions[0])
    assert history.events[0].text == "Synthetic Grok question" * (2 if kind == "legitimate" else 1)
    assert history.state == ("partial" if kind == "conflict" else "complete")
    assert all("CONFLICTING" not in (e.text or "") for e in history.events)
    if kind == "tool":
        tool = next(e for e in history.events if e.role == "tool_call")
        assert tool.payload["status"] == "completed"
        assert next(e for e in history.events if e.role == "tool_result").text == "Synthetic output"


def test_replayed_packet_in_confirmed_tail_keeps_history_search_and_counts(tmp_path):
    root = SourceRoot.create("grok", tmp_path / "native")
    path = make(root.path)
    make(root.path, "neighbor", cwd=tmp_path / "neighbor-project")
    source = path / "updates.jsonl"
    first = source.read_text().splitlines()[0]
    cfg = Config(tmp_path / "manager", tmp_path / "config", [root], "replace")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        refresh(cfg, catalog)
        session = next(s for s in catalog.sessions() if s.native_id == "grok-one")
        with source.open("a") as stream:
            stream.write(first + "\n")
        for _ in range(2):
            refresh(cfg, catalog)
            current = catalog.get(session.display_id)
            events = catalog.events(current.session_uid)
            assert events[0]["text"] == "Synthetic Grok question"
            assert not catalog.matching_ids("questionSynthetic")
            metrics = summarize(catalog, [current])["metrics"]
            assert metrics["messages"]["value"] == 2 and metrics["messages"]["complete"]
            assert metrics["total_tokens"]["value"] == 15
