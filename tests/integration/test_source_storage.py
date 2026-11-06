import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sessions_manager.cli import app
from sessions_manager.discovery import refresh
from sessions_manager.statistics import summarize
from tests.support.cleanup_case import case


def bytes_under(root):
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def test_shared_codex_storage_is_separate_cached_and_not_per_session(tmp_path, monkeypatch):
    with case(tmp_path, "codex") as (service, root, uid, path, neighbor):
        expected = bytes_under(root.path)
        selected = [service.catalog.get(uid)]
        # Statistics must not rescan native directories on opening/filtering.
        monkeypatch.setattr("os.scandir", lambda *a, **kw: pytest.fail("unexpected native scan"))
        result = summarize(service.catalog, selected, selection={"project": selected[0].cwd})
        assert result["metrics"]["known_session_bytes"]["value"] is None
        storage = result["source_storage"]
        assert storage["value"] == expected
        assert storage["scope"] == "whole_catalogued_history_roots"
        assert storage["complete"] and storage["cached"]
        assert storage["as_of"] is not None
        assert storage["selected_roots"] == storage["known_roots"] == 1
        assert storage["roots"][0]["path"] == str(root.path)


def test_overlapping_grok_roots_do_not_duplicate_storage_bytes(tmp_path):
    from sessions_manager.models import SourceRoot

    with case(tmp_path, "grok") as (service, root, uid, path, neighbor):
        expected = bytes_under(root.path)
        nested = SourceRoot.create("grok", root.path / "sessions", namespace="copy")
        service.config.roots.append(nested)
        refresh(service.config, service.catalog)
        storage = summarize(service.catalog, service.catalog.sessions())["source_storage"]
        assert storage["value"] == expected
        assert storage["selected_roots"] == 2
        assert storage["known_roots"] == 2
        assert sum(r["value"] for r in storage["roots"]) == 2 * expected
        assert storage["complete"]


def test_missing_source_preserves_cached_bytes_and_marks_storage_stale(tmp_path):
    with case(tmp_path, "codex") as (service, root, uid, path, neighbor):
        before = summarize(service.catalog, service.catalog.sessions())["source_storage"]
        root.path.rename(tmp_path / "temporarily-offline")
        refresh(service.config, service.catalog)
        after = summarize(service.catalog, service.catalog.sessions())["source_storage"]
        assert after["value"] == before["value"]
        assert after["as_of"] == before["as_of"]
        assert not after["complete"] and after["roots"][0]["stale"]


def test_cleanup_marks_previous_source_storage_observation_stale(tmp_path):
    from tests.integration.test_cleanup_recovery import run_action

    with case(tmp_path) as (service, root, uid, path, neighbor):
        before = summarize(service.catalog, service.catalog.sessions())["source_storage"]
        run_action(service, "trash", uid)
        after = summarize(service.catalog, service.catalog.sessions())["source_storage"]
        assert not after["complete"] and after["roots"][0]["stale"]
        assert after["as_of"] == before["as_of"]
        refresh(service.config, service.catalog)
        fresh = summarize(service.catalog, service.catalog.sessions())["source_storage"]
        assert fresh["complete"] and fresh["value"] < before["value"]


@pytest.mark.parametrize("exists", [True, False])
def test_empty_and_unavailable_storage_are_distinct(tmp_path, exists):
    from sessions_manager.catalog import Catalog
    from sessions_manager.config import Config
    from sessions_manager.models import SourceRoot

    root = SourceRoot.create("codex", tmp_path / "native")
    if exists:
        root.path.mkdir()
    cfg = Config(tmp_path / "manager", tmp_path / "config", [root], "replace")
    with Catalog(cfg.data_dir) as catalog:
        refresh(cfg, catalog)
        storage = summarize(catalog, [])["source_storage"]
        assert storage["value"] == (0 if exists else None)
        assert storage["complete"] == exists


def test_cli_storage_json_and_human_explain_whole_source_scope(isolated, tmp_path):
    from tests.support.codex_factory import make

    config, data = isolated
    native = tmp_path / "codex"
    make(native, "one", rollout=False)
    make(native, "two", rollout=False)
    config.write_text(
        'discovery_roots_mode="replace"\n[[sources]]\nprovider="codex"\npath='
        + repr(str(native))
        + "\n"
    )
    base = ["--config", str(config), "--data-dir", str(data)]
    runner = CliRunner()
    result = runner.invoke(app, [*base, "--format", "json", "stats"])
    assert result.exit_code == 0, result.output
    storage = json.loads(result.stdout)["data"]["source_storage"]
    assert storage["value"] == bytes_under(native)
    human = runner.invoke(app, [*base, "stats"])
    assert human.exit_code == 0, human.output
    assert "Source storage" in human.output
    assert "whole history roots" in human.output
    assert "not reclaimable" in human.output


def test_storage_does_not_follow_links_or_claim_denied_tree_is_empty(tmp_path, monkeypatch):
    import os

    from sessions_manager.models import SourceRoot
    from sessions_manager.storage import measure

    root = SourceRoot.create("claude", tmp_path / "source")
    histories = root.path / "projects"
    histories.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "unrelated").write_text("SYNTHETIC OUTSIDE")
    (histories / "link").symlink_to(outside, target_is_directory=True)
    assert measure(root)["files"] == {}
    assert not measure(root)["complete"]
    scan = os.scandir

    def denied(path):
        if Path(path) == histories:
            raise PermissionError("synthetic denied listing")
        return scan(path)

    monkeypatch.setattr(os, "scandir", denied)
    observation = measure(root)
    assert not observation["complete"] and not observation["known"]
    assert observation["reason"] == "storage_unavailable"


def test_conflicting_shared_file_observations_do_not_become_known_zero(tmp_path):
    from sessions_manager.models import SourceRoot

    with case(tmp_path, "codex") as (service, root, uid, path, neighbor):
        other = SourceRoot.create("codex", root.path, namespace="copy")
        service.config.roots.append(other)
        refresh(service.config, service.catalog)
        with service.catalog.writer() as db:
            for index, configured in enumerate(service.config.roots):
                db.execute(
                    "UPDATE source_storage SET payload=? WHERE root_id=?",
                    (
                        json.dumps(
                            {
                                "files": {
                                    "synthetic-shared-file": {
                                        "bytes": 10 + index,
                                        "mtime_ns": index,
                                    }
                                },
                                "known": True,
                                "complete": True,
                                "as_of": 1000,
                            }
                        ),
                        configured.root_id,
                    ),
                )
        storage = summarize(service.catalog, service.catalog.sessions())["source_storage"]
        assert storage["value"] is None
        assert not storage["complete"]
        assert storage["reason"] == "storage_observation_conflict"


def test_storage_source_filter_keeps_unavailable_roots_in_default_coverage(tmp_path):
    from sessions_manager.models import SourceRoot

    with case(tmp_path, "codex") as (service, root, uid, path, neighbor):
        service.config.roots.append(SourceRoot.create("grok", tmp_path / "missing-grok"))
        refresh(service.config, service.catalog)
        all_roots = summarize(service.catalog, service.catalog.sessions(), selection={})[
            "source_storage"
        ]
        assert all_roots["selected_roots"] == 2 and all_roots["known_roots"] == 1
        assert not all_roots["complete"]
        filtered = summarize(
            service.catalog, service.catalog.sessions(), selection={"providers": ["codex"]}
        )["source_storage"]
        assert filtered["selected_roots"] == 1 and filtered["complete"]
