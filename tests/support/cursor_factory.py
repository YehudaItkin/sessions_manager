import hashlib
import json
import sqlite3
from pathlib import Path


def varint(number):
    out = bytearray()
    while number > 127:
        out.append((number & 127) | 128)
        number >>= 7
    out.append(number)
    return bytes(out)


def wire(field, value):
    if isinstance(value, str):
        value = value.encode()
    return varint((field << 3) | 2) + varint(len(value)) + value


def make(root, native="cursor-one", cwd=None, text="Synthetic Cursor question", *, context=None):
    root = Path(root)
    cwd = str(cwd or root / "project")
    Path(cwd).mkdir(parents=True, exist_ok=True)
    workspace = hashlib.md5(str(Path(cwd).resolve()).encode()).hexdigest()
    path = root / "chats" / workspace / native
    path.mkdir(parents=True, exist_ok=True)
    (path / "meta.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "cwd": cwd,
                "createdAtMs": 1767225600000,
                "updatedAtMs": 1767225601000,
                "hasConversation": True,
            }
        )
    )
    meta = {
        "agentId": native,
        "latestRootBlobId": "root",
        "name": "Cursor synthetic",
        "createdAt": 1767225600000,
        "lastUsedModel": "synthetic",
        "blobEncryptionKey": "SYNTHETIC-SECRET-NOT-FOR-CATALOG",
    }
    blobs = {
        "root": wire(8, "turn"),
        "turn": wire(1, wire(1, "user") + wire(2, "step")),
        "user": wire(1, text),
        "step": wire(1, wire(1, "Synthetic answer")),
        "orphan": wire(1, "Never visible orphan"),
    }
    if context is not None:
        details = b"".join(
            varint(number << 3) + varint(value)
            for number, value in enumerate(context, 1)
            if value is not None
        )
        blobs["root"] += wire(5, details)
    with sqlite3.connect(path / "store.db") as db:
        db.execute("CREATE TABLE blobs(id TEXT PRIMARY KEY,data BLOB)")
        db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO meta VALUES ('0',?)", (json.dumps(meta).encode().hex(),))
        db.executemany("INSERT INTO blobs VALUES (?,?)", blobs.items())
    db.close()
    return path
