from sessions_manager.models import SourceRoot
from sessions_manager.sources.codex import Adapter
from tests.support.codex_factory import make


def test_catalog_without_rollout_still_discovered(tmp_path):
    make(tmp_path, rollout=False)
    result = Adapter(SourceRoot.create("codex", tmp_path)).discover()
    assert result.complete
    session = result.sessions[0]
    assert session.native_id == "codex-one"
    assert session.created_at == 1767225600123
    assert session.capabilities["cleanup"].reason == "native_cascade_unbounded"
    assert session.capabilities["resume"].state == "unavailable"


def test_verified_paginated_history_is_resumable_without_rollout(tmp_path):
    import sqlite3

    from tests.support.cleanup_case import version_cli

    make(tmp_path, rollout=False)
    with sqlite3.connect(tmp_path / "state_5.sqlite") as db:
        db.execute("ALTER TABLE threads ADD COLUMN history_mode TEXT")
        db.execute("UPDATE threads SET history_mode='paginated'")
    root = SourceRoot.create(
        "codex",
        tmp_path,
        resume_context="native",
        executable_path=version_cli(tmp_path, "0.166.0", "codex"),
    )
    session = Adapter(root).discover().sessions[0]
    assert session.capabilities["resume"].state == "supported"
    assert session.extra["history_mode"] == "paginated"


def test_future_history_mode_is_not_assumed_resumable(tmp_path):
    import sqlite3

    from tests.support.cleanup_case import version_cli

    make(tmp_path, rollout=False)
    with sqlite3.connect(tmp_path / "state_5.sqlite") as db:
        db.execute("ALTER TABLE threads ADD COLUMN history_mode TEXT")
        db.execute("UPDATE threads SET history_mode='future'")
    root = SourceRoot.create(
        "codex",
        tmp_path,
        resume_context="native",
        executable_path=version_cli(tmp_path, "0.166.0", "codex"),
    )
    assert Adapter(root).discover().sessions[0].capabilities["resume"].state == "unavailable"


def test_paginated_catalog_without_persisted_history_is_not_resume_proof(tmp_path):
    import sqlite3

    from tests.support.cleanup_case import version_cli

    make(tmp_path, rollout=False)
    with sqlite3.connect(tmp_path / "state_5.sqlite") as db:
        db.execute("ALTER TABLE threads ADD COLUMN history_mode TEXT")
        db.execute("UPDATE threads SET history_mode='paginated'")
    with sqlite3.connect(tmp_path / "thread_history_1.sqlite") as db:
        db.execute("DELETE FROM thread_items")
    root = SourceRoot.create(
        "codex",
        tmp_path,
        resume_context="native",
        executable_path=version_cli(tmp_path, "0.166.0", "codex"),
    )
    session = Adapter(root).discover().sessions[0]
    assert session.capabilities["resume"].state == "unavailable"
    assert session.capabilities["resume"].reason == "history_not_recorded"


def test_native_archive_metadata_is_independent_of_hidden_and_presence(tmp_path):
    import sqlite3

    make(tmp_path, "active")
    make(tmp_path, "archived")
    with sqlite3.connect(tmp_path / "state_5.sqlite") as db:
        db.execute("ALTER TABLE threads ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        db.execute("UPDATE threads SET archived=1 WHERE id='archived'")
    sessions = {
        s.native_id: s for s in Adapter(SourceRoot.create("codex", tmp_path)).discover().sessions
    }
    assert sessions["archived"].extra["archived"] is True
    assert sessions["active"].extra["archived"] is False
    assert sessions["archived"].presence == "present" and not sessions["archived"].hidden


def test_closed_checkpointed_codex_store_remains_discoverable_without_sidecar_writes(tmp_path):
    import sqlite3

    make(tmp_path, rollout=False)
    path = tmp_path / "state_5.sqlite"
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.close()
    before = path.read_bytes()
    result = Adapter(SourceRoot.create("codex", tmp_path)).discover()
    assert result.complete and len(result.sessions) == 1
    assert path.read_bytes() == before
    assert not path.with_name(path.name + "-wal").exists()
    assert not path.with_name(path.name + "-shm").exists()


def test_malformed_archive_flag_does_not_hide_healthy_neighbor(tmp_path):
    import sqlite3

    make(tmp_path, "healthy")
    make(tmp_path, "bad")
    with sqlite3.connect(tmp_path / "state_5.sqlite") as db:
        db.execute("ALTER TABLE threads ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        db.execute("UPDATE threads SET archived='invalid' WHERE id='bad'")
    result = Adapter(SourceRoot.create("codex", tmp_path)).discover()
    assert not result.complete
    assert [s.native_id for s in result.sessions] == ["healthy"]
