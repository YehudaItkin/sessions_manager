import pytest

from sessions_manager.models import Failure
from tests.support.cleanup_case import case, tree_bytes


class Crash(BaseException):
    pass


def test_new_companion_invalidates_confirmed_bundle_without_moving_anything(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        original, near = tree_bytes(path), tree_bytes(neighbor)
        plan = service.preview("trash", [uid])
        companion = path.with_suffix("") / "tool-results"
        companion.mkdir(parents=True)
        extra = companion / "late.txt"
        extra.write_text("synthetic late tool output")
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        assert result["items"][0]["state"] == "failed_no_change"
        assert result["items"][0]["error"] == "source_changed"
        assert tree_bytes(path) == original and tree_bytes(neighbor) == near
        assert extra.read_text() == "synthetic late tool output"


def test_restore_changes_entry_and_invalidates_earlier_purge_confirmation(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        trash = result["items"][0]["trash_id"]
        purge = service.preview("purge", [trash])
        restore = service.preview("restore", [trash])
        service.commit("restore", [trash], restore["confirmation_token"])
        with pytest.raises(Failure, match="confirmation_stale"):
            service.commit("purge", [trash], purge["confirmation_token"])
        assert path.exists()
        assert service._entry(trash)[0]["state"] == "restored"


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
        assert not service.catalog.connection.execute(
            "SELECT 1 FROM jsonl_cursors WHERE uid=?", (session.session_uid,)
        ).fetchone()
        assert (
            service.catalog.connection.execute("SELECT count(*) FROM jsonl_cursors").fetchone()[0]
            == 1
        )


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
