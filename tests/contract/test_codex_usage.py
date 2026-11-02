from sessions_manager.models import SourceRoot, identity
from sessions_manager.sources.codex import Adapter
from tests.support.codex_factory import append, make


def test_receipts_not_snapshots_and_foreign_owner(tmp_path):
    path = make(tmp_path)
    record = {
        "type": "token_usage_record",
        "payload": {
            "response_id": "response-one",
            "thread_id": "codex-one",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cached_input_tokens": 3,
                "reasoning_output_tokens": 2,
                "total_tokens": 15,
            },
            "thread_token_usage": {"total_tokens": 1000},
        },
    }
    append(path, record)
    append(path, record)
    foreign = {
        "type": "token_usage_record",
        "payload": {**record["payload"], "response_id": "foreign", "thread_id": "other-thread"},
    }
    append(path, foreign)
    root = SourceRoot.create("codex", tmp_path)
    adapter = Adapter(root)
    usage = adapter.read_usage(adapter.discover().sessions[0])
    assert len(usage.facts) == 2
    assert usage.facts[0].total_tokens == 15
    assert usage.facts[0].input_tokens == 10
    own = identity(root.namespace_id, "codex-one")
    foreign_uid = identity(root.namespace_id, "other-thread")
    assert any(m.session_uid == foreign_uid for m in usage.memberships)
    assert len([m for m in usage.memberships if m.session_uid == own]) == 1


def test_legacy_snapshot_is_replaced_not_added(tmp_path):
    path = make(tmp_path)
    for total in (20, 30):
        append(
            path,
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": total - 5,
                            "output_tokens": 5,
                            "total_tokens": total,
                        }
                    },
                },
            },
        )
    root = SourceRoot.create("codex", tmp_path)
    adapter = Adapter(root)
    usage = adapter.read_usage(adapter.discover().sessions[0])
    assert usage.facts == []
    assert len(usage.snapshots) == 1
    assert usage.snapshots[0].values["total_tokens"] == 30
    assert usage.snapshots[0].summability == "unknown"


def test_counter_reset_does_not_claim_complete_lifetime(tmp_path):
    path = make(tmp_path)
    for total in (100, 20):
        append(
            path,
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": {"total_tokens": total}},
                },
            },
        )
    reader = Adapter(SourceRoot.create("codex", tmp_path))
    usage = reader.read_usage(reader.discover().sessions[0])
    assert usage.state == "partial"
    assert usage.snapshots[0].completeness == "partial"
    assert usage.snapshots[0].values["total_tokens"] == 20


def test_mixed_receipts_and_legacy_snapshot_preserve_unknown_overlap(tmp_path):
    path = make(tmp_path)
    append(
        path,
        {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {"total_tokens": 100}},
            },
        },
    )
    append(
        path,
        {
            "type": "token_usage_record",
            "payload": {
                "response_id": "later",
                "thread_id": "codex-one",
                "usage": {"total_tokens": 10},
            },
        },
    )
    reader = Adapter(SourceRoot.create("codex", tmp_path))
    usage = reader.read_usage(reader.discover().sessions[0])
    assert usage.state == "partial"
    assert len(usage.facts) == len(usage.snapshots) == 1
    assert usage.snapshots[0].summability == "unknown"
