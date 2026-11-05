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


def run_action(service, action, target):
    plan = service.preview(action, [target])
    return service.commit(action, [target], plan["confirmation_token"], assert_closed=True)


def test_purging_old_restored_backup_preserves_current_trash_cache(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        catalog = service.catalog
        session = catalog.get(uid)
        first = run_action(service, "trash", uid)["items"][0]["trash_id"]
        run_action(service, "restore", first)
        second = run_action(service, "trash", uid)["items"][0]["trash_id"]
        before_events = catalog.events(session.session_uid)
        before_cursors = list(
            catalog.connection.execute(
                "SELECT path,payload FROM jsonl_cursors WHERE uid=?", (session.session_uid,)
            )
        )
        run_action(service, "purge", first)
        assert catalog.get(uid).presence == "trashed"
        assert catalog.events(session.session_uid) == before_events
        assert (
            list(
                catalog.connection.execute(
                    "SELECT path,payload FROM jsonl_cursors WHERE uid=?", (session.session_uid,)
                )
            )
            == before_cursors
        )
        assert catalog.connection.execute(
            "SELECT 1 FROM chunks WHERE uid=?", (session.session_uid,)
        ).fetchone()
        assert service._entry(second)[0]["state"] == "trashed"
        run_action(service, "restore", second)
        assert path.exists() and neighbor.exists()


@pytest.mark.parametrize("purged", [False, True])
def test_verified_native_reappearance_revives_same_hidden_session(tmp_path, purged):
    from sessions_manager.discovery import prepare_scan, publish_scan, scan_metadata, scan_root

    with case(tmp_path) as (service, root, uid, path, neighbor):
        original = path.read_bytes()
        catalog = service.catalog
        session = catalog.get(uid)
        catalog.hide([session.session_uid], True)
        trash = run_action(service, "trash", uid)["items"][0]["trash_id"]
        if purged:
            run_action(service, "purge", trash)
        path.write_bytes(original)
        _, arguments = prepare_scan(service.config, catalog)
        publish_scan(catalog, root, scan_metadata(arguments[0]))
        assert catalog.get(uid).presence == ("purged" if purged else "trashed")
        publish_scan(catalog, root, scan_root(arguments[0]))
        revived = catalog.get(uid)
        assert revived.presence == "present"
        assert revived.session_uid == session.session_uid and revived.hidden
        assert catalog.events(session.session_uid)
        assert any(s.session_uid == session.session_uid for s in catalog.sessions())
        if not purged:
            with pytest.raises(Failure, match="destination_conflict"):
                service.preview("restore", [trash])


def test_header_only_reappearance_keeps_tombstone(tmp_path):
    from sessions_manager.discovery import refresh

    with case(tmp_path) as (service, root, uid, path, neighbor):
        trash = run_action(service, "trash", uid)["items"][0]["trash_id"]
        run_action(service, "purge", trash)
        path.write_text('{"type":"summary","summary":"stale header","sessionId":"selected"}\n')
        refresh(service.config, service.catalog)
        assert service.catalog.get(uid).presence == "purged"


def test_codex_projection_without_native_history_cannot_revive_tombstone(tmp_path):
    from sessions_manager.discovery import refresh

    with case(tmp_path, "codex") as (service, root, uid, path, neighbor):
        session = service.catalog.get(uid)
        with service.catalog.writer() as db:
            db.execute("UPDATE sessions SET presence='purged' WHERE uid=?", (session.session_uid,))
        path.unlink()
        refresh(service.config, service.catalog)
        assert service.catalog.get(uid).presence == "purged"


@pytest.mark.parametrize("failure", ["before_directory", "after_directory", "partial_directory"])
def test_terminal_purge_receipt_reconciles_after_restart(tmp_path, monkeypatch, failure):
    from sessions_manager import fsops
    from sessions_manager.catalog import Catalog
    from sessions_manager.cleanup import CleanupService

    with case(tmp_path) as (service, root, uid, path, neighbor):
        trash = run_action(service, "trash", uid)["items"][0]["trash_id"]
        directory = service.config.data_dir / "trash" / trash
        near = tree_bytes(neighbor)
        remove = fsops.remove_owned_tree

        def fail(target):
            if target == directory:
                if failure == "after_directory":
                    remove(target)
                elif failure == "partial_directory":
                    (target / "manifest.json").unlink()
                raise OSError("synthetic terminal cleanup error")
            return remove(target)

        monkeypatch.setattr(fsops, "remove_owned_tree", fail)
        result = run_action(service, "purge", trash)
        assert service._entry(trash)[0]["state"] == "purged"
        assert result["items"][0]["state"] == "purged"
        assert result["items"][0]["cleanup_pending"]
        assert "restore" not in service.trash_list()[0]["available_actions"]
        monkeypatch.setattr(fsops, "remove_owned_tree", remove)
        with Catalog(service.config.data_dir) as restarted:
            retry = CleanupService(service.config, restarted).retry(result["operation_id"])
            assert retry["items"][0]["state"] == "purged"
            assert not retry["items"][0].get("cleanup_pending")
        assert not directory.exists() and tree_bytes(neighbor) == near


def test_crash_after_purge_receipt_preserves_terminal_truth_and_rejects_new_contents(
    tmp_path, monkeypatch
):
    from sessions_manager import fsops
    from sessions_manager.catalog import Catalog
    from sessions_manager.cleanup import CleanupService

    with case(tmp_path) as (service, root, uid, path, neighbor):
        trash = run_action(service, "trash", uid)["items"][0]["trash_id"]
        directory = service.config.data_dir / "trash" / trash
        remove = fsops.remove_owned_tree

        def crash(target):
            if target == directory:
                raise Crash()
            return remove(target)

        monkeypatch.setattr(fsops, "remove_owned_tree", crash)
        with pytest.raises(Crash):
            run_action(service, "purge", trash)
        op = service.trash_list()[0]["operation_id"]
        assert service._entry(trash)[0]["state"] == "purged"
        unknown = directory / "unconfirmed"
        unknown.write_text("new contents")
        monkeypatch.setattr(fsops, "remove_owned_tree", remove)
        with Catalog(service.config.data_dir) as restarted:
            new = CleanupService(service.config, restarted)
            refused = new.retry(op)
            assert refused["items"][0]["state"] == "purged"
            assert refused["items"][0]["error"] == "unknown_trash_artifact"
            assert unknown.read_text() == "new contents"
            unknown.unlink()
            assert not new.retry(op)["items"][0].get("cleanup_pending")
        assert not directory.exists() and neighbor.exists()
