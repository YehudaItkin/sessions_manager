import sqlite3

import pytest

from sessions_manager.models import Failure
from sessions_manager.sources.sqlite_reader import NativeSQLite


def test_read_only_and_no_repair(tmp_path):
    path = tmp_path / "native.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items(id TEXT, value TEXT)")
        db.execute("INSERT INTO items VALUES (?,?)", ("one", "hello"))
        db.execute("CREATE VIEW dangerous AS SELECT * FROM items")
    before = path.read_bytes()
    with NativeSQLite(path, {"items": {"id", "value"}}) as reader:
        assert reader.read("items", ["id", "value"])[0]["value"] == "hello"
        assert reader.connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert reader.connection.execute("PRAGMA trusted_schema").fetchone()[0] == 0
        with pytest.raises(sqlite3.DatabaseError):
            reader.connection.execute("DELETE FROM items")
        with pytest.raises(Failure):
            reader.read("dangerous", ["id"])
    assert path.read_bytes() == before
    assert not path.with_name("native.db-wal").exists()


def test_live_wal_visible_without_change(tmp_path):
    path = tmp_path / "wal.db"
    writer = sqlite3.connect(path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE items(id TEXT)")
    writer.execute("INSERT INTO items VALUES ('committed')")
    writer.commit()
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if not p.name.endswith("-shm")}
    with NativeSQLite(path, {"items": {"id"}}) as reader:
        assert reader.read("items", ["id"])[0]["id"] == "committed"
    assert all((tmp_path / name).read_bytes() == value for name, value in before.items())
    writer.close()


def test_missing_wal_sidecars_are_not_created(tmp_path):
    path = tmp_path / "closed.db"
    with sqlite3.connect(path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE items(id TEXT)")
    writer.close()
    assert not path.with_name("closed.db-wal").exists()
    with pytest.raises(Failure, match="wal_sidecars_unavailable"):
        with NativeSQLite(path, {"items": {"id"}}):
            pass
    assert not path.with_name("closed.db-wal").exists()


def test_attach_and_virtual_tables_are_forbidden(tmp_path):
    path = tmp_path / "native.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items(id TEXT,value TEXT)")
    db.close()
    other = tmp_path / "must-not-exist.db"
    with NativeSQLite(path, {"items": {"id", "value"}}) as reader:
        with pytest.raises(sqlite3.DatabaseError):
            reader.connection.execute("ATTACH DATABASE ? AS external", (str(other),))
        with pytest.raises(sqlite3.DatabaseError):
            reader.connection.execute("PRAGMA query_only=OFF")
    assert not other.exists()
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE items")
        db.execute("CREATE VIRTUAL TABLE items USING fts5(id,value)")
    db.close()
    with pytest.raises(Failure, match="unsupported_native_schema"):
        with NativeSQLite(path, {"items": {"id", "value"}}):
            pass
