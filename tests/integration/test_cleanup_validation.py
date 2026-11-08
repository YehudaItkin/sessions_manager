import json

import pytest
from typer.testing import CliRunner

from sessions_manager.cleanup import digest
from sessions_manager.cli import app
from sessions_manager.models import Failure
from tests.support.cleanup_case import case, tree_bytes


def corrupt_entry(service, trash, kind):
    entry, directory = service._entry(trash)
    entry.pop("state")
    # Stored manifests always start at preview, independently of the mutable row state.
    entry["state"] = "preview"
    if kind == "root":
        entry["source_root"] = {}
    elif kind == "artifacts":
        entry["artifacts"] = [123]
    elif kind == "inventory":
        entry["artifacts"][0]["inventory"]["."]["kind"] = "PRIVATE-SENTINEL"
    elif kind == "escape":
        entry["artifacts"][0]["inventory"]["../outside"] = entry["artifacts"][0]["inventory"]["."]
    elif kind == "identity":
        entry["session_uid"] = "different-session"
    elif kind == "owner":
        entry["owner_uid"] = True
    elif kind == "version":
        entry["manifest_version"] = 999
    elif kind == "manifest_scope":
        entry["source_profile"] = "different-profile"
    raw = json.dumps(entry).encode()
    if kind != "manifest_scope":
        (directory / "manifest.json").write_bytes(raw)
    with service.catalog.writer() as db:
        db.execute(
            "UPDATE trash_entries SET payload=?,manifest_digest=? WHERE trash_id=?",
            (raw.decode(), digest((directory / "manifest.json").read_bytes()), trash),
        )


@pytest.mark.parametrize(
    "kind",
    ["root", "artifacts", "inventory", "escape", "identity", "owner", "version", "manifest_scope"],
)
def test_nested_entry_is_rejected_before_listing_preview_or_mutation(tmp_path, kind):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        trash = result["items"][0]["trash_id"]
        corrupt_entry(service, trash, kind)
        retained = tree_bytes(service.config.data_dir / "trash")
        near = tree_bytes(neighbor)
        for action in (
            service.trash_list,
            lambda: service.preview("restore", [trash]),
            lambda: service.preview("purge", [trash]),
        ):
            with pytest.raises(Failure, match="catalog_record_invalid"):
                action()
        assert tree_bytes(service.config.data_dir / "trash") == retained
        assert tree_bytes(neighbor) == near and not path.exists()


@pytest.mark.parametrize("entrypoint", ["listing", "preview", "retry", "commit"])
def test_corrupt_plan_has_safe_failure_before_lifecycle_change(tmp_path, entrypoint, monkeypatch):
    from tests.integration.test_cleanup_recovery import Crash

    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])

        def crash(stage, target):
            if stage == "lifecycle_started":
                raise Crash()

        service.fault = crash
        with pytest.raises(Crash):
            service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        service.fault = None
        op = service.trash_list()[0]["operation_id"]
        with service.catalog.writer() as db:
            targets = json.loads(db.execute("SELECT payload FROM operation_plans").fetchone()[0])
            targets[0]["artifacts"] = ["PRIVATE-SENTINEL"]
            db.execute("UPDATE operation_plans SET payload=?", (json.dumps(targets),))
        before = list(
            map(tuple, service.catalog.connection.execute("SELECT * FROM operation_items"))
        )
        native, near = tree_bytes(path), tree_bytes(neighbor)
        action = {
            "listing": service.trash_list,
            "preview": lambda: service.recovery_preview(op),
            "retry": lambda: service.retry(op, assert_closed=True),
            "commit": lambda: service.commit(
                "trash", [uid], plan["confirmation_token"], assert_closed=True
            ),
        }[entrypoint]
        with pytest.raises(Failure, match="catalog_record_invalid"):
            action()
        assert before == list(
            map(tuple, service.catalog.connection.execute("SELECT * FROM operation_items"))
        )
        assert tree_bytes(path) == native and tree_bytes(neighbor) == near


def test_cli_nested_entry_failure_is_content_free(tmp_path, monkeypatch):
    import sessions_manager.cli as cli

    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        trash = result["items"][0]["trash_id"]
        corrupt_entry(service, trash, "inventory")
        # Keep the test's real journal open across each CLI boundary.
        monkeypatch.setattr(cli, "cleanup_service", lambda obj: service)
        monkeypatch.setattr(service.catalog, "close", lambda: None)
        for arguments in (
            ["trash", "list"],
            ["trash", "restore", trash],
            ["trash", "purge", trash],
        ):
            response = CliRunner().invoke(app, ["--format", "json", *arguments])
            assert response.exit_code == 6, response.output
            assert json.loads(response.stdout)["error"]["code"] == "catalog_record_invalid"
            assert "PRIVATE-SENTINEL" not in response.output


def test_missing_progress_field_fails_before_lifecycle_change(tmp_path):
    from tests.integration.test_cleanup_recovery import Crash

    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])

        def crash(stage, target):
            if stage == "lifecycle_started":
                raise Crash()

        service.fault = crash
        with pytest.raises(Crash):
            service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        service.fault = None
        op = service.trash_list()[0]["operation_id"]
        with service.catalog.writer() as db:
            item = json.loads(db.execute("SELECT payload FROM operation_items").fetchone()[0])
            item.pop("trash_id")
            db.execute("UPDATE operation_items SET payload=?", (json.dumps(item),))
        revision = service.catalog.connection.execute(
            "SELECT lifecycle_revision FROM sessions WHERE uid=?",
            (service.catalog.get(uid).session_uid,),
        ).fetchone()[0]
        with pytest.raises(Failure, match="catalog_record_invalid"):
            service.retry(op, assert_closed=True)
        assert (
            service.catalog.connection.execute(
                "SELECT lifecycle_revision FROM sessions WHERE uid=?",
                (service.catalog.get(uid).session_uid,),
            ).fetchone()[0]
            == revision
        )


def test_valid_legacy_entry_defaults_remain_restorable(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        trash = result["items"][0]["trash_id"]
        entry, directory = service._entry(trash)
        entry["state"] = "preview"
        for key in ("manifest_version", "snapshot_verified_at", "conflict_reason"):
            entry.pop(key)
        for key in ("enabled", "default_root", "last_scan_id", "health"):
            entry["source_root"].pop(key)
        raw = json.dumps(entry).encode()
        (directory / "manifest.json").write_bytes(raw)
        with service.catalog.writer() as db:
            db.execute(
                "UPDATE trash_entries SET payload=?,manifest_digest=? WHERE trash_id=?",
                (raw.decode(), digest(raw), trash),
            )
        assert service.trash_list()[0]["available_actions"] == ["restore", "purge"]
        plan = service.preview("restore", [trash])
        assert (
            service.commit("restore", [trash], plan["confirmation_token"])["items"][0]["state"]
            == "restored"
        )


@pytest.mark.parametrize("action", ["restore", "purge"])
@pytest.mark.parametrize("field", ["session_uid", "artifacts"])
def test_entry_plan_scope_cannot_change_lifecycle_or_files(tmp_path, action, field):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])
        trash = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)[
            "items"
        ][0]["trash_id"]
        plan = service.preview(action, [trash])
        with service.catalog.writer() as db:
            targets = json.loads(
                db.execute(
                    "SELECT payload FROM operation_plans WHERE plan_id=?", (plan["plan_id"],)
                ).fetchone()[0]
            )
            if field == "session_uid":
                targets[0][field] = next(
                    s.session_uid for s in service.catalog.sessions() if s.native_id == "neighbor"
                )
            else:
                targets[0][field] = []
            db.execute(
                "UPDATE operation_plans SET payload=? WHERE plan_id=?",
                (json.dumps(targets), plan["plan_id"]),
            )
        before = tree_bytes(service.config.data_dir / "trash")
        revisions = list(
            map(
                tuple,
                service.catalog.connection.execute(
                    "SELECT uid,lifecycle_revision,lifecycle_pending FROM sessions"
                ),
            )
        )
        with pytest.raises(Failure, match="catalog_record_invalid"):
            service.commit(action, [trash], plan["confirmation_token"])
        assert tree_bytes(service.config.data_dir / "trash") == before
        assert revisions == list(
            map(
                tuple,
                service.catalog.connection.execute(
                    "SELECT uid,lifecycle_revision,lifecycle_pending FROM sessions"
                ),
            )
        )
        assert not path.exists() and neighbor.exists()
