import json
import zlib

import pytest

from sessions_manager.models import Failure
from sessions_manager.sources.jsonl_cursor import VERSION, JSONLCursor


@pytest.mark.parametrize("payload", [[], {"version": VERSION}, {"version": VERSION, "offset": -1}])
def test_corrupt_checkpoint_rebuilds_from_native_file(tmp_path, payload):
    path = tmp_path / "history.jsonl"
    path.write_bytes(b'{"type":"user","text":"native"}\n')
    cursor = JSONLCursor({str(path): zlib.compress(json.dumps(payload).encode())})
    assert list(cursor.read(path))[0][1]["text"] == "native"
    assert cursor.entries[str(path)]["audit"]["mode"] == "full"


def test_link_target_change_invalidates_parser_cache(tmp_path):
    target, link = tmp_path / "target", tmp_path / "history.jsonl"
    target.write_bytes(b'{"type":"user","text":"first"}\n')
    link.symlink_to(target)
    cursor = JSONLCursor()
    list(cursor.read(link))
    target.write_bytes(b'{"type":"user","text":"second"}\n')
    assert list(cursor.read(link))[0][1]["text"] == "second"


@pytest.mark.parametrize("change", ["truncate", "replace", "schema"])
def test_cursor_rebuilds_incompatible_prefix(tmp_path, change):
    path = tmp_path / "history.jsonl"
    raw = b'{"type":"user","text":"old"}\n'
    path.write_bytes(raw * 3)
    cursor = JSONLCursor()
    assert len(list(cursor.read(path))) == 3
    stored = cursor.checkpoints()
    if change == "truncate":
        path.write_bytes(raw)
    elif change == "replace":
        replacement = tmp_path / "replacement"
        replacement.write_bytes(raw)
        replacement.replace(path)
    else:
        value = json.loads(zlib.decompress(stored[str(path)]))
        value["version"] = "unknown"
        stored[str(path)] = zlib.compress(json.dumps(value).encode())
    cursor = JSONLCursor(stored)
    rows = list(cursor.read(path))
    assert cursor.entries[str(path)]["audit"]["mode"] == "full"
    assert len(rows) == (3 if change == "schema" else 1)


def test_incomplete_tail_is_retried_without_duplicate_rows(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_bytes(b'{"type":"user","text":"first"}\n{"type":"assistant","text":"par')
    cursor = JSONLCursor()
    rows = []
    with pytest.raises(Failure, match="invalid_native_record"):
        for row in cursor.read(path):
            rows.append(row)
    assert len(rows) == 1
    stored = cursor.checkpoints()
    with path.open("ab") as stream:
        stream.write(b'tial"}\n')
    cursor = JSONLCursor(stored)
    rows = list(cursor.read(path))
    assert [row[1]["text"] for row in rows] == ["first", "partial"]
    assert cursor.entries[str(path)]["audit"]["mode"] == "append_tail"
