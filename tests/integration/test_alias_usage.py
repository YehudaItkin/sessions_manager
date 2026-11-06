import json
import pickle
import shutil

import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import prepare_scan, publish_scan, scan_for_transport, scan_metadata
from sessions_manager.models import SourceRoot
from sessions_manager.sources.base import ScanResult
from sessions_manager.statistics import summarize


def usage_copies(tmp_path, provider, same_root):
    from importlib import import_module

    factory = import_module("tests.support." + provider + "_factory")
    roots = [SourceRoot.create(provider, tmp_path / "a")]
    first = factory.make(roots[0].path, "same", cwd=tmp_path / "project")
    if same_root:
        if provider == "claude":
            second = roots[0].path / "projects" / "other" / first.name
            second.parent.mkdir()
            shutil.copyfile(first, second)
        else:
            second = roots[0].path / "sessions" / "other" / first.name
            shutil.copytree(first, second)
    else:
        roots.append(SourceRoot.create(provider, tmp_path / "b"))
        second = factory.make(roots[1].path, "same", cwd=tmp_path / "project")
    if provider == "codex":
        for path in (first, second):
            factory.append(
                path,
                {
                    "type": "token_usage_record",
                    "payload": {
                        "thread_id": "same",
                        "response_id": "request",
                        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    },
                },
            )
    return roots, first, second


def change_usage(path, provider, variant):
    if provider == "grok":
        path = path / "usage.json"
        if variant == "unknown":
            path.unlink()
        else:
            row = json.loads(path.read_text())
            row["totalTokens"] = 999
            row["outputTokens"] = 989
            path.write_text(json.dumps(row))
    else:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if provider == "claude":
            if variant == "unknown":
                rows[-1]["message"].pop("usage")
            else:
                rows[-1]["message"]["usage"]["output_tokens"] = 999
        elif variant == "unknown":
            rows = [row for row in rows if row["type"] != "token_usage_record"]
        else:
            rows[-1]["payload"]["usage"]["total_tokens"] = 999
            rows[-1]["payload"]["usage"]["output_tokens"] = 989
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))


@pytest.mark.parametrize(
    "provider,same_root",
    [("claude", True), ("grok", True), ("claude", False), ("grok", False), ("codex", False)],
)
@pytest.mark.parametrize("variant", ["matching", "conflict", "unknown"])
@pytest.mark.parametrize("reverse", [False, True])
def test_alias_usage_agreement_is_independent_of_history(
    tmp_path, provider, same_root, variant, reverse
):
    roots, first, second = usage_copies(tmp_path, provider, same_root)
    if variant != "matching":
        change_usage(second, provider, variant)
    before = {p: p.read_bytes() for r in roots for p in r.path.rglob("*") if p.is_file()}
    cfg = Config(tmp_path / "manager", tmp_path / "config", roots, "replace")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        for _ in range(2):
            _, args = prepare_scan(cfg, catalog)
            for i, root in enumerate(roots):
                publish_scan(catalog, root, scan_metadata(args[i]))
            ordered = list(reversed(list(enumerate(roots)))) if reverse else list(enumerate(roots))
            for i, root in ordered:
                result = scan_for_transport(args[i])
                if reverse:
                    result.sessions.reverse()
                publish_scan(catalog, root, pickle.loads(pickle.dumps(result)))
            session = catalog.sessions()[0]
            assert len(catalog.sessions()) == 1 and session.history_state == "complete"
            assert not session.extra.get("identity_conflict")
            assert catalog.events(session.session_uid)
            metric = summarize(catalog, [session])["metrics"]["total_tokens"]
            if variant == "matching":
                assert metric["value"] == (20 if provider == "claude" else 15)
                assert metric["complete"]
            else:
                assert metric["value"] is None and not metric["complete"]
                assert session.capabilities["usage"].reason in (
                    "usage_identity_conflict",
                    "usage_binding_unverified",
                )
        assert all(p.read_bytes() == raw for p, raw in before.items())
        uid = session.session_uid
        catalog.hide([uid], True)
        # Verified disappearance must restore the remaining copy's own evidence,
        # including when the absent root finishes after the surviving root.
        if same_root:
            shutil.rmtree(second) if second.is_dir() else second.unlink()
        else:
            if provider == "codex":
                import sqlite3

                with sqlite3.connect(roots[1].path / "state_5.sqlite") as db:
                    db.execute("DELETE FROM threads")
            else:
                shutil.rmtree(second) if second.is_dir() else second.unlink()
        _, args = prepare_scan(cfg, catalog)
        for i, root in enumerate(roots):
            publish_scan(catalog, root, scan_for_transport(args[i]))
        current = catalog.get(uid)
        metric = summarize(catalog, [current])["metrics"]["total_tokens"]
        assert current.hidden and metric["complete"]
        assert metric["value"] == (20 if provider == "claude" else 15)


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_failed_alias_peer_cannot_leave_usage_complete(tmp_path, outcome):
    roots, _, _ = usage_copies(tmp_path, "grok", False)
    cfg = Config(tmp_path / "manager", tmp_path / "config", roots, "replace")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        for cycle in range(2):
            _, args = prepare_scan(cfg, catalog)
            for i, root in enumerate(roots):
                result = (
                    ScanResult(complete=False, reason=outcome)
                    if cycle and i
                    else scan_for_transport(args[i])
                )
                publish_scan(catalog, root, result)
        session = catalog.sessions()[0]
        metric = summarize(catalog, [session])["metrics"]["total_tokens"]
        assert metric["value"] is None and not metric["complete"]


def test_conflicting_alias_usage_does_not_rewrite_shared_healthy_receipt(tmp_path):
    from tests.support.claude_factory import make

    roots, _, second = usage_copies(tmp_path, "claude", True)
    make(roots[0].path, "neighbor", cwd=tmp_path / "project", message_id="api-one")
    change_usage(second, "claude", "conflict")
    cfg = Config(tmp_path / "manager", tmp_path / "config", roots, "replace")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        _, args = prepare_scan(cfg, catalog)
        publish_scan(catalog, roots[0], scan_for_transport(args[0]))
        neighbor = next(s for s in catalog.sessions() if s.native_id == "neighbor")
        metric = summarize(catalog, [neighbor])["metrics"]["total_tokens"]
        assert metric["value"] == 20 and metric["complete"]


def test_purge_removes_retained_per_location_usage_evidence(tmp_path, fake_executable):
    from sessions_manager.cleanup import CleanupService
    from sessions_manager.discovery import refresh
    from tests.integration.test_local_aliases import local_copies

    with local_copies(tmp_path, fake_executable) as (cfg, catalog, root, first, second):
        refresh(cfg, catalog)
        second.unlink()
        refresh(cfg, catalog)
        session = catalog.sessions()[0]
        service = CleanupService(cfg, catalog)
        plan = service.preview("trash", [session.display_id])
        result = service.commit(
            "trash", [session.display_id], plan["confirmation_token"], assert_closed=True
        )
        trash = result["items"][0]["trash_id"]
        plan = service.preview("purge", [trash])
        service.commit("purge", [trash], plan["confirmation_token"])
        assert all(
            row[0] is None
            for row in catalog.connection.execute(
                "SELECT payload FROM locations WHERE uid=?", (session.session_uid,)
            )
        )


def test_usage_reconciliation_retains_shared_event_revision_guard(tmp_path):
    from tests.support.claude_factory import make

    roots, _, _ = usage_copies(tmp_path, "claude", True)
    neighbor = make(roots[0].path, "neighbor", cwd=tmp_path / "project", message_id="api-one")
    neighbor.write_text(
        neighbor.read_text().replace("Synthetic answer", "Different shared revision")
    )
    cfg = Config(tmp_path / "manager", tmp_path / "config", roots, "replace")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        _, args = prepare_scan(cfg, catalog)
        publish_scan(catalog, roots[0], scan_for_transport(args[0]))
        selected = next(s for s in catalog.sessions() if s.native_id == "same")
        assert selected.history_state == selected.search_state == "partial"
        assert selected.extra["history_conflict"] == "shared_event_revision_conflict"
