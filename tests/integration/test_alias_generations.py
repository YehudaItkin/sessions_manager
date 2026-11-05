from contextlib import contextmanager

import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import adapter, prepare_scan, publish_scan, scan_metadata, scan_root
from sessions_manager.models import Failure, SourceRoot
from sessions_manager.sources.base import ScanResult
from tests.support.claude_factory import make


@contextmanager
def aliases(tmp_path, binary, *, conflict=False):
    roots = [
        SourceRoot.create(
            "claude",
            tmp_path / name,
            executable_path=binary,
            executable_version="synthetic",
            resume_context="native",
        )
        for name in ("a", "b")
    ]
    paths = [make(r.path, "same", cwd=tmp_path / "project") for r in roots]
    if conflict:
        paths[1].write_text(paths[1].read_text().replace("Synthetic answer", "different answer"))
    make(roots[1].path, "unique", message_id="unique-api")
    cfg = Config(tmp_path / "manager", tmp_path / "config", roots, "replace")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        yield cfg, catalog, roots, paths


@pytest.mark.parametrize("first", [0, 1])
@pytest.mark.parametrize("conflict", [False, True])
def test_known_alias_actions_wait_for_current_generation_agreement(
    tmp_path, fake_executable, first, conflict
):
    with aliases(tmp_path, fake_executable, conflict=conflict) as (cfg, catalog, roots, paths):
        _, arguments = prepare_scan(cfg, catalog)
        for i in range(2):
            publish_scan(catalog, roots[i], scan_metadata(arguments[i]))
        result = scan_root(arguments[first])
        publish_scan(catalog, roots[first], result)
        session = next(s for s in catalog.sessions() if s.native_id == "same")
        assert session.capabilities["resume"].state != "supported"
        assert session.history_state != "complete"
        assert catalog.events(session.session_uid)
        publish_scan(catalog, roots[1 - first], scan_root(arguments[1 - first]))
        session = catalog.get(session.display_id)
        assert (session.capabilities["resume"].state == "supported") == (not conflict)
        assert session.capabilities["cleanup"].state != "supported"
        if not conflict:
            assert session.history_state == "complete"
            # Starting another refresh cannot reuse an old proof as fresh agreement.
            _, again = prepare_scan(cfg, catalog)
            assert catalog.get(session.display_id).capabilities["resume"].state != "supported"
            publish_scan(catalog, roots[first], scan_metadata(again[first]))
            publish_scan(catalog, roots[first], scan_root(again[first]))
            assert catalog.get(session.display_id).capabilities["resume"].state != "supported"


def test_fresh_single_root_resume_cannot_bypass_catalog_alias_guard(tmp_path, fake_executable):
    from sessions_manager.launch import build_request, revalidate

    with aliases(tmp_path, fake_executable) as (cfg, catalog, roots, paths):
        _, arguments = prepare_scan(cfg, catalog)
        for i in range(2):
            publish_scan(catalog, roots[i], scan_metadata(arguments[i]))
        publish_scan(catalog, roots[1], scan_root(arguments[1]))
        fresh = next(s for s in adapter(roots[1]).discover().sessions if s.native_id == "same")
        with pytest.raises(Failure, match="identity_binding_unverified"):
            revalidate(build_request(roots[1], fresh, cfg.data_dir))


@pytest.mark.parametrize("outcome", ["failed", "cancelled", "absent"])
def test_alias_failure_does_not_block_unrelated_session_and_empty_scan_releases_guard(
    tmp_path, fake_executable, outcome
):
    with aliases(tmp_path, fake_executable) as (cfg, catalog, roots, paths):
        _, arguments = prepare_scan(cfg, catalog)
        # A late metadata phase must not displace B's available full snapshot.
        publish_scan(catalog, roots[1], scan_metadata(arguments[1]))
        publish_scan(catalog, roots[1], scan_root(arguments[1]))
        publish_scan(catalog, roots[0], scan_metadata(arguments[0]))
        same = next(s for s in catalog.sessions() if s.native_id == "same")
        assert same.root_id == roots[1].root_id
        if outcome == "absent":
            paths[0].unlink()
            result = scan_root(arguments[0])
        else:
            result = ScanResult(complete=False, reason=outcome)
        publish_scan(catalog, roots[0], result)
        same = catalog.get(same.display_id)
        assert (same.capabilities["resume"].state == "supported") == (outcome == "absent")
        unique = next(s for s in catalog.sessions() if s.native_id == "unique")
        assert unique.capabilities["resume"].state == "supported"
        assert same.root_id == roots[1].root_id


def test_verified_alias_resume_rechecks_every_copy(tmp_path, fake_executable):
    from sessions_manager.launch import build_request, revalidate

    with aliases(tmp_path, fake_executable) as (cfg, catalog, roots, paths):
        _, arguments = prepare_scan(cfg, catalog)
        for i in range(2):
            publish_scan(catalog, roots[i], scan_root(arguments[i]))
        same = next(s for s in catalog.sessions() if s.native_id == "same")
        root = next(r for r in roots if r.root_id == same.root_id)
        request = build_request(root, same, cfg.data_dir)
        revalidate(request)
        peer = paths[0] if same.root_id == roots[1].root_id else paths[1]
        peer.write_text(peer.read_text().replace("Synthetic answer", "changed answer"))
        with pytest.raises(Failure, match="identity_binding_unverified"):
            revalidate(request)
        from sessions_manager.cleanup import CleanupService

        with pytest.raises(Failure, match="multiple_locations_unverified"):
            CleanupService(cfg, catalog).preview("trash", [same.display_id])


def test_alias_identity_includes_conversation_graph(tmp_path, fake_executable):
    import json

    with aliases(tmp_path, fake_executable) as (cfg, catalog, roots, paths):
        rows = [json.loads(line) for line in paths[1].read_text().splitlines()]
        rows[-1]["parentUuid"] = "different-parent"
        paths[1].write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        _, arguments = prepare_scan(cfg, catalog)
        for i in range(2):
            publish_scan(catalog, roots[i], scan_root(arguments[i]))
        same = next(s for s in catalog.sessions() if s.native_id == "same")
        assert same.capabilities["resume"].reason == "identity_conflict"


def test_raw_resume_rejects_dangling_manager_directory(tmp_path, fake_executable):
    from sessions_manager.launch import build_request

    with aliases(tmp_path, fake_executable) as (cfg, catalog, roots, paths):
        fresh = next(s for s in adapter(roots[0]).discover().sessions if s.native_id == "same")
        dangling = tmp_path / "dangling-manager"
        dangling.symlink_to(tmp_path / "missing-manager", target_is_directory=True)
        with pytest.raises(Failure, match="unsafe_directory_path"):
            build_request(roots[0], fresh, dangling)


def test_worker_alias_evidence_preserves_history_search_chunks(tmp_path, fake_executable):
    from sessions_manager.discovery import scan_for_transport

    with aliases(tmp_path, fake_executable) as (cfg, catalog, roots, paths):
        for path in paths:
            path.write_text(
                path.read_text().replace("Synthetic answer", "alias transport body needle")
            )
        _, arguments = prepare_scan(cfg, catalog)
        for i in range(2):
            publish_scan(catalog, roots[i], scan_for_transport(arguments[i]))
        same = next(s for s in catalog.sessions() if s.native_id == "same")
        assert same.history_state == "complete"
        assert catalog.events(same.session_uid)[1]["text"] == "alias transport body needle"
        assert catalog.matching_ids("alias transport body needle") == {same.session_uid}
