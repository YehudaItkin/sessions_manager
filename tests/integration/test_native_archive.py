"""Synthetic native graph tests; only the fake native RPC writer changes fixtures."""

import json
import sqlite3
from contextlib import contextmanager

import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.models import Failure, SourceRoot
from tests.support.cleanup_case import version_cli
from tests.support.codex_factory import make


@contextmanager
def archive_case(tmp_path, monkeypatch):
    from sessions_manager.native_archive import ArchiveService

    home = tmp_path / "home"
    for name in ("parent", "child", "prior", "neighbor"):
        make(home, name, rollout=False)
    with sqlite3.connect(home / "state_5.sqlite") as db:
        db.execute("ALTER TABLE threads ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        db.execute("ALTER TABLE threads ADD COLUMN history_mode TEXT DEFAULT 'paginated'")
        db.execute("UPDATE threads SET archived=1 WHERE id='prior'")
        for name in ("child", "prior"):
            db.execute(
                "INSERT INTO thread_spawn_edges VALUES (?,?,?)", ("parent", name, "completed")
            )
    root = SourceRoot.create(
        "codex",
        home,
        executable_path=version_cli(tmp_path, "0.166.0", "codex"),
        resume_context="native",
    )
    cfg = Config(tmp_path / "manager", tmp_path / "config", [root], "replace")
    cfg.prepare()
    calls = []
    behavior = {"lost": False, "partial": False}

    def flags():
        with sqlite3.connect(home / "state_5.sqlite") as db:
            return dict(db.execute("SELECT id,archived FROM threads"))

    class Client:
        def __init__(self, root):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def call(self, method, params):
            tid = params["threadId"]
            calls.append((method, tid))
            with sqlite3.connect(home / "state_5.sqlite") as db:
                affected = [tid]
                for current in affected:
                    affected.extend(
                        r[0]
                        for r in db.execute(
                            "SELECT child_thread_id FROM thread_spawn_edges WHERE parent_thread_id=?",
                            (current,),
                        )
                    )
                if behavior["partial"]:
                    affected = [tid]
                for member in affected:
                    db.execute(
                        "UPDATE threads SET archived=? WHERE id=?",
                        (method == "thread/archive", member),
                    )
            if behavior["lost"]:
                behavior["lost"] = False
                raise OSError("synthetic lost reply after native commit")
            return {}

    monkeypatch.setattr("sessions_manager.fsops.open_handles", lambda paths: False)
    with Catalog(cfg.data_dir) as catalog:
        refresh(cfg, catalog)
        service = ArchiveService(cfg, catalog, client_factory=Client)
        uid = next(s.display_id for s in catalog.sessions() if s.native_id == "parent")
        yield service, root, uid, flags, calls, behavior, Client


def perform(service, action, uid):
    plan = service.preview(action, uid)
    return service.commit(action, uid, plan["confirmation_token"], assert_closed=True)


def test_preview_binds_full_graph_and_preserves_prior_flags_after_restore(tmp_path, monkeypatch):
    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        plan = service.preview("archive", uid)
        assert {m["native_id"] for m in plan["members"]} == {"parent", "child", "prior"}
        assert calls == [] and flags()["parent"] == 0
        with pytest.raises(Failure, match="closed_assertion_required"):
            service.commit("archive", uid, plan["confirmation_token"])
        result = service.commit("archive", uid, plan["confirmation_token"], assert_closed=True)
        assert result["state"] == "complete"
        assert flags() == dict(parent=1, child=1, prior=1, neighbor=0)
        assert [s.native_id for s in service.catalog.sessions()] == ["neighbor"]
        assert (
            service.commit("archive", uid, plan["confirmation_token"], assert_closed=True) == result
        )
        # Restart before restoring; native unarchive itself cascades over the prior child.
        from sessions_manager.native_archive import ArchiveService

        with Catalog(service.config.data_dir) as restarted:
            new = ArchiveService(service.config, restarted, client_factory=client)
            assert perform(new, "unarchive", uid)["state"] == "complete"
        assert flags() == dict(parent=0, child=0, prior=1, neighbor=0)
        assert ("thread/archive", "prior") in calls


def test_changed_graph_rejects_confirmation_before_native_mutation(tmp_path, monkeypatch):
    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        plan = service.preview("archive", uid)
        with sqlite3.connect(root.path / "state_5.sqlite") as db:
            db.execute("INSERT INTO thread_spawn_edges VALUES ('parent','neighbor','completed')")
        with pytest.raises(Failure, match="archive_source_changed"):
            service.commit("archive", uid, plan["confirmation_token"], assert_closed=True)
        assert calls == [] and flags()["neighbor"] == 0


@pytest.mark.parametrize("failure", ["lost_reply", "partial_cascade", "crash_after_intent"])
def test_native_partial_and_uncertain_outcome_retry_same_operation(tmp_path, monkeypatch, failure):
    class Crash(BaseException):
        pass

    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        plan = service.preview("archive", uid)
        if failure == "crash_after_intent":

            def fault(stage):
                if stage == "before_native":
                    raise Crash()

            service.fault = fault
            with pytest.raises(Crash):
                service.commit("archive", uid, plan["confirmation_token"], assert_closed=True)
            result = service.operations()[0]
        else:
            behavior["lost"] = failure == "lost_reply"
            behavior["partial"] = failure == "partial_cascade"
            result = service.commit("archive", uid, plan["confirmation_token"], assert_closed=True)
            if failure == "lost_reply":
                assert result["state"] == "recovery_required"
        from sessions_manager.native_archive import ArchiveService

        with Catalog(service.config.data_dir) as restarted:
            new = ArchiveService(service.config, restarted, client_factory=client)
            assert new.retry(result["operation_id"], assert_closed=True)["state"] == "complete"
        assert flags() == dict(parent=1, child=1, prior=1, neighbor=0)
        assert all(tid != "neighbor" for method, tid in calls)


def test_retry_never_expands_scope_and_history_changes_conflict(tmp_path, monkeypatch):
    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        behavior["lost"] = True
        result = perform(service, "archive", uid)
        with sqlite3.connect(root.path / "state_5.sqlite") as db:
            db.execute("INSERT INTO thread_spawn_edges VALUES ('parent','neighbor','completed')")
        before = len(calls)
        retry = service.retry(result["operation_id"], assert_closed=True)
        assert retry["state"] == "recovery_required" and retry["error"] == "archive_source_changed"
        assert len(calls) == before and flags()["neighbor"] == 0


@pytest.mark.parametrize("guard", ["active", "open_handle", "alias"])
def test_native_archive_safety_guards(tmp_path, monkeypatch, guard):
    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        if guard == "active":
            with service.catalog.writer() as db:
                db.execute(
                    "UPDATE sessions SET payload=json_set(payload,'$.activity','active') WHERE native_id='child'"
                )
        elif guard == "open_handle":
            monkeypatch.setattr("sessions_manager.fsops.open_handles", lambda paths: True)
        else:
            with service.catalog.writer() as db:
                db.execute(
                    "UPDATE sessions SET payload=json_set(payload,'$.extra.identity_conflict','identity_binding_unverified') WHERE native_id='child'"
                )
        with pytest.raises(Failure):
            service.preview("archive", uid)
        assert calls == []


def test_archive_reconciles_action_capabilities_and_resume_binding(tmp_path, monkeypatch):
    from sessions_manager.launch import build_request, revalidate

    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        assert service.catalog.get(uid).capabilities["resume"].state == "supported"
        perform(service, "archive", uid)
        assert service.catalog.get(uid).capabilities["resume"].state != "supported"
        perform(service, "unarchive", uid)
        session = service.catalog.get(uid)
        assert session.capabilities["resume"].state == "supported"
        revalidate(build_request(root, session, service.config.data_dir))


def test_archive_rejects_missing_rollout_reference_outside_native_home(tmp_path, monkeypatch):
    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        with sqlite3.connect(root.path / "state_5.sqlite") as db:
            db.execute(
                "UPDATE threads SET rollout_path=? WHERE id='child'",
                (str(tmp_path / "outside/missing.jsonl"),),
            )
        with pytest.raises(Failure, match="path_outside_source_root"):
            service.preview("archive", uid)
        assert calls == []


def test_bounded_archive_graph_handles_deep_chains_without_recursion_error():
    from sessions_manager.native_archive import descendants

    graph = {str(i): [str(i + 1)] for i in range(1200)}
    assert len(descendants(graph, "0")) == 1201


def test_recovery_journal_remains_inspectable_when_source_configuration_is_removed(
    tmp_path, monkeypatch
):
    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        behavior["lost"] = True
        result = perform(service, "archive", uid)
        service.config.roots = []
        assert service.operations()[0]["operation_id"] == result["operation_id"]
        retry = service.retry(result["operation_id"], assert_closed=True)
        assert retry["state"] == "recovery_required"
        assert retry["error"] == "archive_profile_unverified"


def test_declared_version_cannot_enable_unverified_native_archive_binary(tmp_path, monkeypatch):
    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        path = root.executable_path
        path.write_text(path.read_text().replace("0.166.0", "0.167.0"))
        root.executable_version = "0.166.0"
        root._detected_version = False
        with pytest.raises(Failure, match="archive_profile_unverified"):
            service.preview("archive", uid)
        assert calls == []


def test_corrupt_persisted_archive_plan_is_rejected_before_native_call(tmp_path, monkeypatch):
    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        plan = service.preview("archive", uid)
        with service.catalog.writer() as db:
            row = db.execute("SELECT token,payload FROM native_archive_plans").fetchone()
            stored = json.loads(row["payload"])
            stored["desired"]["child"] = "false"
            db.execute(
                "UPDATE native_archive_plans SET payload=? WHERE token=?",
                (json.dumps(stored), row["token"]),
            )
        with pytest.raises(Failure, match="archive_journal_invalid"):
            service.commit("archive", uid, plan["confirmation_token"], assert_closed=True)
        assert calls == []


def test_uncertain_unarchive_restores_preexisting_child_flag_on_restart(tmp_path, monkeypatch):
    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        perform(service, "archive", uid)
        behavior["lost"] = True
        result = perform(service, "unarchive", uid)
        assert result["state"] == "recovery_required"
        assert flags()["prior"] == 0
        assert service.retry(result["operation_id"], assert_closed=True)["state"] == "complete"
        assert flags() == dict(parent=0, child=0, prior=1, neighbor=0)


def test_external_archive_unarchive_preserves_descendants_current_flags(tmp_path, monkeypatch):
    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        client(root).call("thread/archive", {"threadId": "parent"})
        assert perform(service, "unarchive", uid)["state"] == "complete"
        assert flags() == dict(parent=0, child=1, prior=1, neighbor=0)


def test_native_startup_failure_allows_fresh_preview_without_pending_mutation(
    tmp_path, monkeypatch
):
    from sessions_manager.native_archive import ArchiveService

    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):

        class BrokenClient:
            def __init__(self, root):
                pass

            def __enter__(self):
                raise OSError("synthetic startup failure")

            def __exit__(self, *args):
                pass

        broken = ArchiveService(service.config, service.catalog, client_factory=BrokenClient)
        result = perform(broken, "archive", uid)
        assert result["state"] == "failed_no_change"
        assert calls == [] and flags()["parent"] == 0
        assert service.preview("archive", uid)["confirmation_token"]


def test_archive_does_not_mark_old_index_fresh_when_native_history_changed(tmp_path, monkeypatch):
    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        with sqlite3.connect(root.path / "thread_history_1.sqlite") as db:
            item = json.loads(
                db.execute(
                    "SELECT item_json FROM thread_items WHERE thread_id='parent'"
                ).fetchone()[0]
            )
            item["content"][0]["text"] = "NEW-NATIVE-CONTEXT"
            db.execute(
                "UPDATE thread_items SET item_json=? WHERE thread_id='parent'", (json.dumps(item),)
            )
        perform(service, "archive", uid)
        perform(service, "unarchive", uid)
        refresh(service.config, service.catalog)
        assert (
            service.catalog.events(service.catalog.get(uid).session_uid)[0]["text"]
            == "NEW-NATIVE-CONTEXT"
        )


def test_reader_started_before_archive_cannot_publish_old_archive_flags(tmp_path, monkeypatch):
    from sessions_manager.discovery import prepare_scan, publish_scan, scan_root

    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        _, args = prepare_scan(service.config, service.catalog)
        old_result = scan_root(args[0])
        perform(service, "archive", uid)
        publish_scan(service.catalog, root, old_result)
        assert service.catalog.get(uid).extra["archived"] is True
        assert [s.native_id for s in service.catalog.sessions()] == ["neighbor"]


def test_fresh_resume_cannot_bypass_pending_unarchive_recovery(tmp_path, monkeypatch):
    from sessions_manager.discovery import adapter
    from sessions_manager.launch import build_request, revalidate

    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        perform(service, "archive", uid)
        behavior["lost"] = True
        assert perform(service, "unarchive", uid)["state"] == "recovery_required"
        fresh = next(s for s in adapter(root).discover().sessions if s.native_id == "parent")
        with pytest.raises(Failure, match="archive_operation_pending"):
            revalidate(build_request(root, fresh, service.config.data_dir))
