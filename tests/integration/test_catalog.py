from dataclasses import replace

import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.config import ensure_private
from sessions_manager.models import Failure, Session, SourceRoot


def test_generation_hide_tombstone_and_bound_parameters(tmp_path):
    data = tmp_path / "manager"
    ensure_private(data)
    root = SourceRoot.create("claude", tmp_path / "native")
    session = Session.build(root, "id' OR 1=1 --", root.path / "one")
    with Catalog(data) as catalog:
        catalog.publish(root, [session], complete=True)
        catalog.hide([session.session_uid], True)
        catalog.publish(root, [replace(session, title="new")], complete=True)
        assert catalog.get(session.session_uid).hidden
        catalog.publish(root, [], complete=False)
        assert catalog.get(session.session_uid).presence != "missing"
        catalog.publish(root, [], complete=True)
        assert catalog.get(session.session_uid).presence == "missing"
        catalog.publish(root, [session], complete=True)
        assert catalog.get(session.session_uid).hidden
        with catalog.reader() as reader:
            assert reader.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(Failure):
            catalog.get("not-a-session")
    assert (data / "catalog.sqlite3").stat().st_mode & 0o777 == 0o600


def test_failed_publish_is_atomic(tmp_path):
    ensure_private(tmp_path / "manager")
    root = SourceRoot.create("codex", tmp_path / "native")
    session = Session.build(root, "one", root.path / "one")
    with Catalog(tmp_path / "manager") as catalog:
        catalog.publish(root, [session], complete=True)
        with pytest.raises(AttributeError):
            catalog.publish(root, [replace(session, title="bad"), object()], complete=True)
        assert catalog.get(session.session_uid).title is None


def test_foreign_and_future_catalog_are_never_migrated(tmp_path):
    import sqlite3

    root = tmp_path / "foreign"
    ensure_private(root)
    path = root / "catalog.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE user_data(value TEXT)")
    db.commit()
    db.close()
    path.chmod(0o600)
    before = path.read_bytes()
    with pytest.raises(Failure, match="unsupported_catalog"):
        Catalog(root)
    assert path.read_bytes() == before
    own = tmp_path / "own"
    ensure_private(own)
    with Catalog(own):
        pass
    db = sqlite3.connect(own / "catalog.sqlite3")
    db.execute("PRAGMA user_version=99")
    db.commit()
    db.close()
    before = (own / "catalog.sqlite3").read_bytes()
    with pytest.raises(Failure, match="unsupported_catalog"):
        Catalog(own)
    assert (own / "catalog.sqlite3").read_bytes() == before


def test_invalid_persisted_session_fails_safely_without_rewriting(tmp_path):
    import pytest

    from sessions_manager.models import Failure

    root = SourceRoot.create("claude", tmp_path / "native")
    session = Session.build(root, "one", root.path / "one")
    with Catalog(tmp_path / "data") as catalog:
        catalog.publish(root, [session], complete=True)
        catalog.connection.execute(
            "UPDATE sessions SET payload=json_set(payload,'$.presence','invalid-private-value')"
        )
        catalog.connection.commit()
        with pytest.raises(Failure, match="catalog_record_invalid"):
            catalog.sessions()
        assert catalog.connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_phase10_migrates_v1_records_and_marks_new_schema(tmp_path):
    import sqlite3

    data = tmp_path / "manager"
    root = SourceRoot.create("claude", tmp_path / "native")
    session = Session.build(root, "legacy", root.path / "legacy")
    with Catalog(data) as catalog:
        catalog.publish(root, [session], complete=True)
        catalog.hide([session.session_uid], True)
    with sqlite3.connect(data / "catalog.sqlite3") as old:
        old.execute("ALTER TABLE sessions DROP COLUMN current_trash_id")
        old.execute("ALTER TABLE locations DROP COLUMN payload")
        old.execute("PRAGMA user_version=1")
    with Catalog(data) as upgraded:
        assert upgraded.get(session.display_id).hidden
        assert upgraded.get(session.display_id).presence == "present"
        assert upgraded.connection.execute("PRAGMA user_version").fetchone()[0] == 3
        location = upgraded.connection.execute("SELECT payload FROM locations").fetchone()
        assert location[0] is None


def test_native_archive_rows_are_retained_but_excluded_from_active_catalog(tmp_path):
    root = SourceRoot.create("codex", tmp_path / "native")
    active = Session.build(root, "active", root.path / "one")
    archived = Session.build(root, "archived", root.path / "two", extra={"archived": True})
    with Catalog(tmp_path / "data") as catalog:
        catalog.publish(root, [active, archived], complete=True)
        catalog.hide([archived.session_uid], True)
        assert [s.native_id for s in catalog.sessions()] == ["active"]
        assert len(catalog.sessions(include_missing=True)) == 2
        assert catalog.get(archived.display_id).hidden


def test_archive_capability_migration_retains_v2_session_and_marks_schema(tmp_path):
    import sqlite3

    data = tmp_path / "data"
    root = SourceRoot.create("codex", tmp_path / "native")
    session = Session.build(root, "old-v2", root.path / "old-v2")
    with Catalog(data) as catalog:
        catalog.publish(root, [session], complete=True)
        catalog.hide([session.session_uid], True)
    with sqlite3.connect(data / "catalog.sqlite3") as legacy:
        legacy.execute(
            "UPDATE sessions SET payload=json_remove(payload,'$.capabilities.archive','$.capabilities.unarchive')"
        )
        legacy.execute("PRAGMA user_version=2")
    with Catalog(data) as upgraded:
        assert upgraded.connection.execute("PRAGMA user_version").fetchone()[0] == 3
        found = upgraded.get(session.display_id)
        assert found.hidden and found.capabilities["archive"].state == "unavailable"
        assert found.capabilities["unarchive"].state == "unavailable"
