import pytest

from sessions_manager.models import Failure
from tests.support.cleanup_case import case, tree_bytes


class Crash(BaseException):
    pass


@pytest.mark.parametrize(
    "stage",
    [
        "before_copy",
        "after_copy",
        "after_fsync",
        "after_hash",
        "backup_file",
        "backup_verified",
        "before_rename",
        "after_rename",
        "journal_move",
        "trash_verified",
    ],
)
def test_crash_reconciles_files_and_original_operation(tmp_path, stage):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        original = tree_bytes(path)
        near = tree_bytes(neighbor)
        plan = service.preview("trash", [uid])

        def fault(current, target):
            if current == stage:
                raise Crash()

        service.fault = fault
        with pytest.raises(Crash):
            service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        service.fault = None
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        assert result["items"][0]["state"] == "trashed"
        assert tree_bytes(neighbor) == near
        trash = result["items"][0]["trash_id"]
        restore = service.preview("restore", [trash])
        service.commit("restore", [trash], restore["confirmation_token"])
        assert tree_bytes(path) == original


def test_restore_conflict_preserves_both_and_separate_purge(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        trash = result["items"][0]["trash_id"]
        path.write_text("new conflicting work")
        with pytest.raises(Failure, match="destination_conflict"):
            service.preview("restore", [trash])
        assert path.read_text() == "new conflicting work"
        purge = service.preview("purge", [trash])
        result = service.commit("purge", [trash], purge["confirmation_token"])
        assert result["items"][0]["state"] == "purged"
        assert path.read_text() == "new conflicting work"
        with pytest.raises(Failure):
            service.preview("purge", ["../escape"])


def test_low_disk_keeps_source_bytes(tmp_path, monkeypatch):
    from collections import namedtuple

    import sessions_manager.fsops as fsops

    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])
        before = tree_bytes(path)
        usage = namedtuple("usage", "total used free")
        monkeypatch.setattr(fsops.shutil, "disk_usage", lambda p: usage(100, 100, 0))
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        assert result["items"][0]["state"] == "failed_no_change"
        assert tree_bytes(path) == before


def test_mixed_batch_reports_per_target_and_preserves_failed_source(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        neighbor_id = next(
            s.display_id for s in service.catalog.sessions() if s.native_id == "neighbor"
        )
        plan = service.preview("trash", [uid, neighbor_id])
        neighbor.write_text(neighbor.read_text() + "\n")
        result = service.commit(
            "trash", [uid, neighbor_id], plan["confirmation_token"], assert_closed=True
        )
        assert [item["state"] for item in result["items"]] == ["trashed", "failed_no_change"]
        assert neighbor.exists() and not path.exists()


def test_purge_clears_cached_transcript_and_retry_uses_operation_id(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])

        def crash(stage, target):
            if stage == "after_rename":
                raise Crash()

        service.fault = crash
        with pytest.raises(Crash):
            service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        service.fault = None
        listing = service.trash_list()
        assert listing[0]["state"] == "recovery_required"
        result = service.retry(listing[0]["operation_id"], assert_closed=True)
        trash = result["items"][0]["trash_id"]
        plan = service.preview("purge", [trash])
        assert plan["known_bytes"] >= 2 * sum(
            r.get("size", 0)
            for a in service._entry(trash)[0]["artifacts"]
            for r in a["inventory"].values()
        )
        service.commit("purge", [trash], plan["confirmation_token"])
        session = service.catalog.get(uid)
        assert session.preview is None and session.title is None
        assert service.catalog.events(session.session_uid) == []


def test_restore_crash_retries_without_overwriting(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        original = tree_bytes(path)
        plan = service.preview("trash", [uid])
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        trash = result["items"][0]["trash_id"]
        restore = service.preview("restore", [trash])

        def crash(stage, target):
            if stage == "restore_rename":
                raise Crash()

        service.fault = crash
        with pytest.raises(Crash):
            service.commit("restore", [trash], restore["confirmation_token"])
        service.fault = None
        result = service.commit("restore", [trash], restore["confirmation_token"])
        assert result["items"][0]["state"] == "restored"
        assert tree_bytes(path) == original
