import json
from pathlib import Path


def make(root, native="grok-one", cwd=None, text="Synthetic Grok question"):
    root = Path(root)
    cwd = str(cwd or root / "project")
    Path(cwd).mkdir(parents=True, exist_ok=True)
    path = root / "sessions" / "encoded" / native
    path.mkdir(parents=True, exist_ok=True)
    (path / "summary.json").write_text(
        json.dumps(
            {
                "info": {"id": native, "cwd": cwd},
                "created_at": "2026-01-01T00:00:00Z",
                "last_active_at": "2026-01-01T00:00:01Z",
                "generated_title": "Grok synthetic",
                "chat_format_version": 1,
                "current_model_id": "synthetic",
            }
        )
    )
    rows = [
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "method": "session/update",
            "params": {
                "sessionId": native,
                "update": {
                    "sessionUpdate": "user_message_chunk",
                    "content": {"type": "text", "text": text},
                    "_meta": {"eventId": native + "-user"},
                },
            },
        },
        {
            "timestamp": "2026-01-01T00:00:01Z",
            "method": "session/update",
            "params": {
                "sessionId": native,
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "Synthetic answer"},
                    "_meta": {"eventId": native + "-assistant"},
                },
            },
        },
    ]
    (path / "updates.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    (path / "usage.json").write_text(
        json.dumps(
            {
                "inputTokens": 10,
                "outputTokens": 5,
                "cachedReadTokens": 3,
                "cacheCreationTokens": 2,
                "totalTokens": 15,
                "modelCalls": 1,
                "turnCount": 1,
            }
        )
    )
    return path
