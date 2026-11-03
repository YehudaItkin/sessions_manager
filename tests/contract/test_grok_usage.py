import json

from sessions_manager.models import SourceRoot
from sessions_manager.sources.grok import Adapter
from tests.support.grok_factory import make


def test_native_session_envelope_preserves_tokens_without_summing_turns(tmp_path):
    path = make(tmp_path)
    totals = json.loads((path / "usage.json").read_text())
    (path / "usage.json").write_text(
        json.dumps(
            {
                "sessionId": "grok-one",
                "session": totals,
                "turns": [{"totalTokens": 900}],
                "usageIsIncomplete": True,
            }
        )
    )
    reader = Adapter(SourceRoot.create("grok", tmp_path))
    usage = reader.read_usage(reader.discover().sessions[0])
    assert usage.snapshots[0].values["input_tokens"] == 10
    assert usage.snapshots[0].values["total_tokens"] == 15
    assert usage.state == "partial"
    (path / "usage.json").write_text(json.dumps({"sessionId": "other", "session": totals}))
    rejected = reader.read_usage(reader.discover().sessions[0])
    assert rejected.state != "complete" and not rejected.snapshots


def test_single_snapshot_unknown_summability_and_nulls(tmp_path):
    path = make(tmp_path)
    raw = json.loads((path / "usage.json").read_text())
    raw["turns"] = [{"totalTokens": 999}]
    raw["usageIsIncomplete"] = True
    (path / "usage.json").write_text(json.dumps(raw))
    adapter = Adapter(SourceRoot.create("grok", tmp_path))
    session = adapter.discover().sessions[0]
    usage = adapter.read_usage(session)
    assert usage.facts == [] and len(usage.snapshots) == 1
    assert usage.snapshots[0].values["total_tokens"] == 15
    assert usage.snapshots[0].summability == "unknown"
    assert usage.state == "partial"
    (path / "usage.json").write_text('{"inputTokens":0}')
    usage = adapter.read_usage(session)
    assert usage.snapshots[0].values["input_tokens"] == 0
    assert usage.snapshots[0].values["output_tokens"] is None
    assert usage.snapshots[0].values["total_tokens"] is None
