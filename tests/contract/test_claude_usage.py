from sessions_manager.models import SourceRoot
from sessions_manager.sources.claude import Adapter
from tests.support.claude_factory import append, make


def test_normalized_cache_and_monotonic_last_valid_usage(tmp_path):
    path = make(tmp_path)
    append(
        path,
        {
            "type": "assistant",
            "sessionId": "claude-one",
            "message": {
                "id": "api-one",
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 3,
                    "cache_creation_input_tokens": 2,
                    "output_tokens": 8,
                    "cache_creation": {"ephemeral_5m_input_tokens": 2},
                },
            },
        },
    )
    adapter = Adapter(SourceRoot.create("claude", tmp_path))
    usage = adapter.read_usage(adapter.discover().sessions[0])
    fact = usage.facts[0]
    assert fact.input_tokens == 15 and fact.total_tokens == 23
    append(
        path,
        {
            "type": "assistant",
            "sessionId": "claude-one",
            "message": {
                "id": "api-one",
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 3,
                    "cache_creation_input_tokens": 2,
                    "output_tokens": 1,
                },
            },
        },
    )
    usage = adapter.read_usage(adapter.discover().sessions[0])
    assert usage.facts[0].output_tokens == 8
    assert usage.facts[0].completeness == "partial"
