import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.cleanup import CleanupService
from sessions_manager.models import Failure
from tests.support.cleanup_case import case, tree_bytes


@pytest.mark.parametrize(
    "stage",
    [
        "entry_intent",
        "entry_directory",
        "entry_manifest",
        "before_copy",
        "backup_verified",
        "before_rename",
    ],
)
def test_no_source_change_actions_and_staging_purge_survive_restart(tmp_path, stage):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        native, near = tree_bytes(path), tree_bytes(neighbor)
        plan = service.preview("trash", [uid])

        def fail(current, target):
            if current == stage:
                raise OSError("synthetic failure")

        service.fault = fail
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        item = result["items"][0]
        assert item["state"] == "failed_no_change"
        assert tree_bytes(path) == native and tree_bytes(neighbor) == near
        with Catalog(service.config.data_dir) as catalog:
            restarted = CleanupService(service.config, catalog)
            listing = restarted.trash_list()
            if stage == "entry_intent":
                assert not listing
                return
            if listing[0]["kind"] == "operation":
                assert item.get("cleanup_pending")
                final = restarted.retry(result["operation_id"], assert_closed=True)
                assert final["items"][0]["state"] == "failed_no_change"
                assert not final["items"][0].get("cleanup_pending")
                listing = restarted.trash_list()
            row = listing[0]
            assert not row["recoverable_copy"]
            assert set(row["available_actions"]) == {"new_preview", "purge"}
            assert "retry_same_confirmation" not in row["available_actions"]
            # Repeating the old confirmation stays terminal and does not create a new copy.
            restarted.retry(result["operation_id"], assert_closed=True)
            new = restarted.preview("trash", [uid])
            assert new["confirmation_token"] != plan["confirmation_token"]
            purge = restarted.preview("purge", [row["trash_id"]])
            outcome = restarted.commit("purge", [row["trash_id"]], purge["confirmation_token"])
            assert outcome["items"][0]["state"] == "purged"
            assert tree_bytes(path) == native and tree_bytes(neighbor) == near


@pytest.mark.parametrize("change", ["none", "after_preview", "unrelated", "during_preview"])
def test_partial_backup_has_exact_confirmed_purge_or_preserves_unexpected_version(
    tmp_path, monkeypatch, change
):
    import sessions_manager.fsops as fsops

    with case(tmp_path) as (service, root, uid, path, neighbor):
        native, near = tree_bytes(path), tree_bytes(neighbor)
        original = fsops.shutil.copyfileobj

        def partial(reader, writer, *args):
            writer.write(reader.read(5))
            raise OSError("synthetic partial copy")

        monkeypatch.setattr(fsops.shutil, "copyfileobj", partial)
        plan = service.preview("trash", [uid])
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        monkeypatch.setattr(fsops.shutil, "copyfileobj", original)
        trash = result["items"][0]["trash_id"]
        entry, directory = service._entry(trash)
        backup = directory / "backup" / "0"
        assert backup.read_bytes() == path.read_bytes()[:5]
        if change == "unrelated":
            backup.write_bytes(b"WRONG")
            with pytest.raises(Failure):
                service.preview("purge", [trash])
            assert backup.read_bytes() == b"WRONG"
        elif change == "during_preview":
            inventory = fsops.inventory

            def substitute(target, boundary):
                if target == directory:
                    backup.write_bytes(b"WRONG")
                return inventory(target, boundary)

            monkeypatch.setattr(fsops, "inventory", substitute)
            with pytest.raises(Failure):
                service.preview("purge", [trash])
            assert backup.read_bytes() == b"WRONG"
        else:
            purge = service.preview("purge", [trash])
            if change == "after_preview":
                backup.write_bytes(b"WRONG")
                outcome = service.commit("purge", [trash], purge["confirmation_token"])
                assert outcome["items"][0]["state"] == "recovery_required"
                assert backup.read_bytes() == b"WRONG"
            else:
                outcome = service.commit("purge", [trash], purge["confirmation_token"])
                assert outcome["items"][0]["state"] == "purged"
                assert not directory.exists()
        assert tree_bytes(path) == native and tree_bytes(neighbor) == near
