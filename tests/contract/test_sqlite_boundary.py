def test_explicit_closed_snapshot_reads_checkpointed_wal_without_creating_sidecars(tmp_path):
    import sqlite3

    from sessions_manager.sources.sqlite_reader import NativeSQLite

    path = tmp_path / "closed.sqlite"
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE threads(id TEXT)")
    db.execute("INSERT INTO threads VALUES ('synthetic')")
    db.commit()
    db.close()
    assert not path.with_name(path.name + "-wal").exists()
    before = path.read_bytes()
    with NativeSQLite(path, {"threads": {"id"}}, closed_snapshot=True) as reader:
        assert reader.read("threads", ["id"]) == [{"id": "synthetic"}]
    assert path.read_bytes() == before
    assert not path.with_name(path.name + "-wal").exists()
    assert not path.with_name(path.name + "-shm").exists()


def test_closed_snapshot_option_does_not_ignore_live_wal(tmp_path):
    import sqlite3

    from sessions_manager.sources.sqlite_reader import NativeSQLite

    path = tmp_path / "live.sqlite"
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE threads(id TEXT)")
    db.execute("INSERT INTO threads VALUES ('committed-in-wal')")
    db.commit()
    try:
        before = path.with_name(path.name + "-wal").read_bytes()
        with NativeSQLite(path, {"threads": {"id"}}, closed_snapshot=True) as reader:
            assert reader.read("threads", ["id"])[0]["id"] == "committed-in-wal"
        assert path.with_name(path.name + "-wal").read_bytes() == before
    finally:
        db.close()


def test_closed_snapshot_refuses_new_sidecar_during_read(tmp_path):
    import sqlite3

    import pytest

    from sessions_manager.models import Failure
    from sessions_manager.sources.sqlite_reader import NativeSQLite

    path = tmp_path / "closed.sqlite"
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE threads(id TEXT)")
    db.commit()
    db.close()
    with pytest.raises(Failure, match="source_changed"):
        with NativeSQLite(path, {"threads": {"id"}}, closed_snapshot=True):
            path.with_name(path.name + "-wal").write_bytes(b"synthetic late writer")
