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
