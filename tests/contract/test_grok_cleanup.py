import pytest

from sessions_manager.models import Failure
from tests.support.cleanup_case import case, tree_bytes


def test_grok_local_directory_only(tmp_path):
    with case(tmp_path, "grok") as (service, root, uid, path, neighbor):
        before = tree_bytes(neighbor)
        plan = service.preview("trash", [uid])
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        assert result["items"][0]["state"] == "trashed"
        assert not path.exists() and tree_bytes(neighbor) == before


def test_unknown_shared_search_dependency_disables_cleanup(tmp_path):
    with case(tmp_path, "grok") as (service, root, uid, path, neighbor):
        (root.path / "sessions/search.db").write_text("unknown shared index")
        with pytest.raises(Failure, match="shared_dependency_unverified"):
            service.preview("trash", [uid])


@pytest.mark.parametrize("location", ["home", "sessions", "workspace"])
@pytest.mark.parametrize("name", ["session_search.sqlite", "grok.db", "grok.db-wal"])
def test_shared_index_scope_is_never_mutated_or_partially_trashed(tmp_path, location, name):
    with case(tmp_path, "grok") as (service, root, uid, path, neighbor):
        parent = {"home": root.path, "sessions": root.path / "sessions", "workspace": path.parent}[
            location
        ]
        shared = parent / name
        shared.write_bytes(b"SYNTHETIC shared selected + neighbor records")
        before = tree_bytes(root.path)
        with pytest.raises(Failure, match="shared_dependency_unverified"):
            service.preview("trash", [uid])
        assert tree_bytes(root.path) == before
        assert not service.trash_list()
        assert (
            service.catalog.connection.execute("SELECT count(*) FROM operation_plans").fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("stage", ["before_rename", "after_rename"])
def test_supported_local_grok_bundle_recovers_from_crash_and_restores(tmp_path, stage):
    from tests.integration.test_cleanup_recovery import Crash

    with case(tmp_path, "grok") as (service, root, uid, path, neighbor):
        before, near = tree_bytes(path), tree_bytes(neighbor)
        plan = service.preview("trash", [uid])

        def crash(current, target):
            if current == stage:
                raise Crash()

        service.fault = crash
        with pytest.raises(Crash):
            service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        service.fault = None
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        trash = result["items"][0]["trash_id"]
        restore = service.preview("restore", [trash])
        service.commit("restore", [trash], restore["confirmation_token"])
        assert tree_bytes(path) == before and tree_bytes(neighbor) == near
