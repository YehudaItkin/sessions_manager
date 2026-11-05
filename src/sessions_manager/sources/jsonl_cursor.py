"""Private, whitelisted parser checkpoints; native files are always read-only.

Prefix hashing verifies append, rather than assuming that a larger file is append-only.
Only new complete lines are JSON-decoded. Existing normalizers replay filtered records
so streaming, usage receipts and compaction keep their existing semantics.
"""

import hashlib
import json
import threading
import zlib

from ..models import NORMALIZER_VERSION, Failure
from .base import fingerprint

VERSION = "jsonl-input-2/" + NORMALIZER_VERSION
# Only fields consumed by the supported Claude/Codex/Grok JSONL readers. Unknown
# properties (including credentials/config/environment) never enter the checkpoint.
KEYS = set(
    """
type uuid sessionId session_id cwd version timestamp title message role content id
model usage parentUuid text tool_use_id name input_tokens output_tokens total_tokens
cache_read_input_tokens cache_creation_input_tokens reasoning_output_tokens
cached_input_tokens cache_write_input_tokens payload thread_id response_id info
total_token_usage params update _meta sessionUpdate eventId messageId promptId
toolCallId status agentTimestampMs command output turn_id
""".split()
)


def project(value, depth=0, budget=None):
    if budget is None:
        budget = [100000]
    budget[0] -= 1
    if depth > 64 or budget[0] < 0:
        raise Failure("jsonl_projection_limit", 3)
    if isinstance(value, dict):
        return {key: project(item, depth + 1, budget) for key, item in value.items() if key in KEYS}
    if isinstance(value, list):
        return [project(item, depth + 1, budget) for item in value]
    return value


def valid_checkpoint(value):
    if not isinstance(value, dict) or value.get("version") != VERSION:
        return False
    required = {"fingerprint", "offset", "ordinal", "rows", "prefix_hash", "incomplete", "audit"}
    if not required <= value.keys():
        return False
    return (
        isinstance(value["fingerprint"], dict)
        and all(type(value[key]) is int and value[key] >= 0 for key in ("offset", "ordinal"))
        and isinstance(value["rows"], list)
        and all(
            isinstance(row, list)
            and len(row) == 2
            and type(row[0]) is int
            and 0 <= row[0] < value["ordinal"]
            and isinstance(row[1], dict)
            for row in value["rows"]
        )
        and isinstance(value["prefix_hash"], str)
        and len(value["prefix_hash"]) == 64
        and type(value["incomplete"]) is bool
        and isinstance(value["audit"], dict)
    )


class JSONLCursor:
    def __init__(self, stored=None):
        self.stored = stored or {}
        self.entries = {}
        self.lock = threading.RLock()

    def read(self, path):
        key = str(path)
        with self.lock:
            stamp = fingerprint(path)
            entry = self.entries.get(key)
            if entry is None and key in self.stored:
                try:
                    entry = json.loads(zlib.decompress(self.stored[key]))
                    if not valid_checkpoint(entry):
                        entry = None
                except (ValueError, TypeError, zlib.error):
                    entry = None
            if entry is None or entry.get("fingerprint") != stamp:
                entry = self._read(path, stamp, entry)
            self.entries[key] = entry
        yield from entry["rows"]
        if entry["incomplete"]:
            raise Failure("invalid_native_record", 3)

    def _read(self, path, stamp, previous):
        rows, offset, ordinal = [], 0, 0
        checksum = hashlib.sha256()
        mode, validated = "full", 0
        with path.open("rb", buffering=262144) as stream:
            if (
                previous
                and previous.get("version") == VERSION
                and previous["fingerprint"].get("dev") == stamp.get("dev")
                and previous["fingerprint"].get("inode") == stamp.get("inode")
                and previous["offset"] <= stamp.get("size", 0)
            ):
                remaining = previous["offset"]
                while remaining:
                    block = stream.read(min(262144, remaining))
                    if not block:
                        break
                    checksum.update(block)
                    remaining -= len(block)
                if not remaining and checksum.hexdigest() == previous["prefix_hash"]:
                    offset, ordinal = previous["offset"], previous["ordinal"]
                    rows = list(previous["rows"])
                    mode, validated = "append_tail", offset
                else:
                    checksum = hashlib.sha256()
                    stream.seek(0)
            decoded, incomplete = 0, False
            for raw in stream:
                decoded += len(raw)
                if not raw.endswith(b"\n"):
                    incomplete = True
                    break
                try:
                    value = json.loads(raw) if raw.strip() else None
                    if value is not None and not isinstance(value, dict):
                        raise ValueError()
                    projected = project(value) if value is not None else None
                except (ValueError, UnicodeError, Failure, RecursionError):
                    incomplete = True
                    break
                if value is not None:
                    rows.append([ordinal, projected])
                checksum.update(raw)
                offset += len(raw)
                ordinal += 1
            if fingerprint(path) != stamp:
                raise Failure("source_changed", 3)
        return {
            "version": VERSION,
            "fingerprint": stamp,
            "offset": offset,
            "ordinal": ordinal,
            "prefix_hash": checksum.hexdigest(),
            "rows": rows,
            "incomplete": incomplete,
            "audit": {
                "mode": mode,
                "validated_prefix_bytes": validated,
                "decoded_tail_bytes": decoded,
            },
        }

    def checkpoints(self):
        return {
            path: zlib.compress(json.dumps(entry, ensure_ascii=False).encode(), 1)
            for path, entry in self.entries.items()
        }
