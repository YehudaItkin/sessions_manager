from sessions_manager.models import SourceRoot
from sessions_manager.sources.claude import Adapter
from tests.support.claude_factory import append, make


def test_graph_tools_and_stream_snapshot_dedup(tmp_path):
    path = make(tmp_path)
    append(
        path,
        {
            "type": "assistant",
            "uuid": "chunk",
            "parentUuid": "claude-one-user",
            "sessionId": "claude-one",
            "message": {
                "id": "api-one",
                "content": [{"type": "text", "text": "Synthetic answer extended"}],
            },
        },
    )
    append(
        path,
        {
            "type": "user",
            "uuid": "tool-result",
            "sessionId": "claude-one",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "tool-one", "content": "tool output"}
                ]
            },
        },
    )
    adapter = Adapter(SourceRoot.create("claude", tmp_path))
    history = adapter.read_history(adapter.discover().sessions[0])
    assert history.state == "complete"
    assert [e.role for e in history.events] == ["user", "assistant", "tool_result"]
    assert history.events[1].text == "Synthetic answer extended"
    assert history.events[1].parent_id == "claude-one-user"
