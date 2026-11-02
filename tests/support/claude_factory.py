import json
from pathlib import Path


def make(
    root, native="claude-one", cwd=None, text="Synthetic Claude question", *, message_id="api-one"
):
    root = Path(root)
    cwd = str(cwd or root / "project")
    Path(cwd).mkdir(parents=True, exist_ok=True)
    path = root / "projects" / "encoded-is-not-cwd" / (native + ".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "type": "user",
            "uuid": native + "-user",
            "sessionId": native,
            "cwd": cwd,
            "version": "2.1.263",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {"role": "user", "content": text},
        },
        {
            "type": "assistant",
            "uuid": native + "-answer",
            "parentUuid": native + "-user",
            "sessionId": native,
            "cwd": cwd,
            "version": "2.1.263",
            "timestamp": "2026-01-01T00:00:01Z",
            "message": {
                "id": message_id,
                "role": "assistant",
                "model": "synthetic",
                "content": [{"type": "text", "text": "Synthetic answer"}],
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 3,
                    "cache_creation_input_tokens": 2,
                    "output_tokens": 5,
                },
            },
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def append(path, record):
    with path.open("a") as stream:
        stream.write(json.dumps(record) + "\n")
