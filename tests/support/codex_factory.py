import json
import sqlite3
from pathlib import Path


def make(root, native="codex-one", cwd=None, text="Synthetic Codex question", *, rollout=True):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cwd = str(cwd or root / "project")
    Path(cwd).mkdir(parents=True, exist_ok=True)
    file = root / "sessions" / (native + ".jsonl")
    file.parent.mkdir(exist_ok=True)
    with sqlite3.connect(root / "state_5.sqlite") as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS threads(id TEXT PRIMARY KEY, rollout_path TEXT, cwd TEXT, title TEXT, model TEXT, created_at INTEGER, updated_at INTEGER, created_at_ms INTEGER, updated_at_ms INTEGER)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS thread_spawn_edges(parent_thread_id TEXT, child_thread_id TEXT, status TEXT)"
        )
        db.execute(
            "INSERT OR REPLACE INTO threads VALUES (?,?,?,?,?,?,?,?,?)",
            (
                native,
                str(file),
                cwd,
                "Codex synthetic",
                "test-model",
                1767225600,
                1767225601,
                1767225600123,
                1767225601123,
            ),
        )
    db.close()
    item = {
        "type": "userMessage",
        "id": "item-" + native,
        "content": [{"type": "inputText", "text": text}],
    }
    with sqlite3.connect(root / "thread_history_1.sqlite") as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS thread_items(thread_id TEXT,turn_id TEXT,item_id TEXT,rollout_ordinal INTEGER,item_json TEXT,item_type TEXT,created_at_ms INTEGER,updated_at_ordinal INTEGER)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS thread_turns(thread_id TEXT,turn_id TEXT,rollout_ordinal INTEGER,status TEXT,started_at INTEGER,completed_at INTEGER,root_turn_id TEXT)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS thread_realtime_items(thread_id TEXT,item_id TEXT,rollout_ordinal INTEGER,created_at_ms INTEGER,item_type TEXT,item_json TEXT)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS thread_history_projection_state(thread_id TEXT,next_rollout_byte_offset INTEGER,next_rollout_ordinal INTEGER)"
        )
        db.execute(
            "INSERT INTO thread_items VALUES (?,?,?,?,?,?,?,?)",
            (native, "turn-one", item["id"], 1, json.dumps(item), item["type"], 1767225600123, 1),
        )
        db.execute("INSERT INTO thread_history_projection_state VALUES (?,?,?)", (native, 0, 2))
    db.close()
    if rollout:
        file.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {"id": native, "cwd": cwd, "timestamp": "2026-01-01T00:00:00Z"},
                }
            )
            + "\n"
        )
    return file


def append(path, record):
    with path.open("a") as stream:
        stream.write(json.dumps(record) + "\n")
