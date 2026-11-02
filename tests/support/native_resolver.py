"""Independent synthetic native lookup; no production parser or launch code imports."""

import hashlib
import json
import sqlite3
from pathlib import Path


def resolve(provider, argv, cwd, home):
    cwd, home = Path(cwd), Path(home)
    if provider == "codex":
        if argv[1] != "resume":
            return None
        native = argv[2]
        with sqlite3.connect((home / "state_5.sqlite").as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute("SELECT rollout_path FROM threads WHERE id=?", (native,)).fetchone()
        return Path(row[0]) if row and Path(row[0]).is_file() else None
    native = argv[argv.index("--resume") + 1]
    if provider == "claude":
        for transcript in (home / "projects").glob("*/*.jsonl"):
            rows = [json.loads(line) for line in transcript.read_text().splitlines() if line]
            if any(row.get("sessionId") == native and row.get("cwd") == str(cwd) for row in rows):
                return transcript
        return None
    if provider == "grok":
        if Path(argv[argv.index("--cwd") + 1]) != cwd:
            return None
        for summary in (home / "sessions").glob("*/*/summary.json"):
            info = json.loads(summary.read_text())["info"]
            if info["id"] == native and info["cwd"] == str(cwd):
                return summary.parent
        return None
    if Path(argv[argv.index("--workspace") + 1]) != cwd:
        return None
    workspace = hashlib.md5(str(cwd.resolve()).encode()).hexdigest()
    directory = home / "chats" / workspace / native
    if not (directory / "store.db").exists():
        return None
    with sqlite3.connect((directory / "store.db").as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT value FROM meta WHERE key='0'").fetchone()
    return directory if row and json.loads(bytes.fromhex(row[0]))["agentId"] == native else None
