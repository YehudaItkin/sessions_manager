import json
from contextlib import contextmanager

import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.cleanup import CleanupService
from sessions_manager.config import Config
from sessions_manager.discovery import (
    prepare_scan,
    publish_scan,
    refresh,
    scan_for_transport,
    scan_metadata,
    scan_root,
)
from sessions_manager.launch import build_request, revalidate
from sessions_manager.models import Failure, SourceRoot
from sessions_manager.statistics import summarize
from tests.support.claude_factory import make


@contextmanager
def local_copies(tmp_path, binary, variant="same"):
    root = SourceRoot.create(
        "claude",
        tmp_path / "native",
        executable_path=binary,
        executable_version="synthetic",
        resume_context="native",
    )
    first = make(root.path, "same", cwd=tmp_path / "project", text="ALPHA synthetic")
    second = root.path / "projects" / "zz-copy" / first.name
    second.parent.mkdir()
    rows = [json.loads(line) for line in first.read_text().splitlines()]
    if variant == "body":
        rows[0]["message"]["content"] = "BETA synthetic"
    elif variant == "cwd":
        moved = tmp_path / "other-project"
        moved.mkdir()
        for row in rows:
            row["cwd"] = str(moved)
    elif variant == "graph":
        rows[-1]["parentUuid"] = "different-parent"
    second.write_text("".join(json.dumps(row) + "\n" for row in rows))
    cfg = Config(tmp_path / "manager", tmp_path / "config", [root], "replace")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        yield cfg, catalog, root, first, second


@pytest.mark.parametrize("variant", ["same", "body", "cwd", "graph"])
@pytest.mark.parametrize("transport", [False, True])
def test_same_root_locations_are_reconciled_before_actions_and_content(
    tmp_path, fake_executable, variant, transport
):
    with local_copies(tmp_path, fake_executable, variant) as (cfg, catalog, root, first, second):
        before = [p.read_bytes() for p in (first, second)]
        _, args = prepare_scan(cfg, catalog)
        publish_scan(catalog, root, scan_metadata(args[0]))
        early = catalog.sessions()[0]
        assert early.capabilities["resume"].state != "supported"
        result = (scan_for_transport if transport else scan_root)(args[0])
        if transport:
            import pickle

            result = pickle.loads(pickle.dumps(result))
        publish_scan(catalog, root, result)
        assert len(catalog.sessions()) == 1
        session = catalog.sessions()[0]
        assert (
            catalog.connection.execute(
                "SELECT COUNT(*) FROM locations WHERE uid=?", (session.session_uid,)
            ).fetchone()[0]
            == 2
        )
        if variant == "same":
            assert session.history_state == "complete"
            assert len(session.extra["alias_bindings"]) == 2
            assert catalog.events(session.session_uid)[0]["text"] == "ALPHA synthetic"
            assert catalog.matching_ids("ALPHA synthetic") == {session.session_uid}
            revalidate(build_request(root, session, cfg.data_dir))
            assert summarize(catalog, [session])["metrics"]["messages"]["value"] == 2
        else:
            assert session.extra["identity_conflict"] == "identity_conflict"
            assert session.history_state == "unavailable"
            assert catalog.events(session.session_uid) == []
            assert not catalog.matching_ids("ALPHA") and not catalog.matching_ids("BETA")
            assert summarize(catalog, [session])["metrics"]["total_tokens"]["value"] is None
            with pytest.raises(Failure, match="identity_conflict"):
                build_request(root, session, cfg.data_dir)
        with pytest.raises(Failure, match="identity_conflict|multiple_locations_unverified"):
            CleanupService(cfg, catalog).preview("trash", [session.display_id])
        assert [p.read_bytes() for p in (first, second)] == before


def test_local_alias_warm_refresh_order_and_disappearance_preserve_identity(
    tmp_path, fake_executable, monkeypatch
):
    from sessions_manager.sources.claude import Adapter

    with local_copies(tmp_path, fake_executable) as (cfg, catalog, root, first, second):
        refresh(cfg, catalog)
        initial = catalog.sessions()[0]
        catalog.hide([initial.session_uid], True)
        actual = Adapter.discover

        def reversed_discovery(reader):
            result = actual(reader)
            result.sessions.reverse()
            return result

        monkeypatch.setattr(Adapter, "discover", reversed_discovery)
        _, args = prepare_scan(cfg, catalog)
        assert catalog.get(initial.display_id).capabilities["resume"].state != "supported"
        publish_scan(catalog, root, scan_metadata(args[0]))
        publish_scan(catalog, root, scan_root(args[0]))
        same = catalog.get(initial.display_id)
        assert same.hidden and same.history_state == "complete"
        assert same.locator == initial.locator
        request = build_request(root, same, cfg.data_dir)
        peer = second if same.locator == str(first) else first
        peer.write_text(peer.read_text().replace("ALPHA", "BETA"))
        with pytest.raises(Failure, match="identity_binding_unverified"):
            revalidate(request)
        refresh(cfg, catalog)
        assert catalog.get(initial.display_id).extra["identity_conflict"] == "identity_conflict"
        peer.unlink()
        refresh(cfg, catalog)
        remaining = catalog.get(initial.display_id)
        assert remaining.hidden and remaining.history_state == "complete"
        assert not remaining.extra.get("identity_conflict")
        assert remaining.capabilities["cleanup"].state == "supported"
        CleanupService(cfg, catalog).preview("trash", [remaining.display_id])


def test_cleanup_refuses_new_local_copy_after_preview(tmp_path):
    from tests.support.cleanup_case import case

    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])
        second = path.parent.parent / "zz-copy" / path.name
        second.parent.mkdir()
        second.write_bytes(path.read_bytes())
        before = [p.read_bytes() for p in (path, second, neighbor)]
        result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        assert result["items"][0]["state"] == "failed_no_change"
        assert [p.read_bytes() for p in (path, second, neighbor)] == before


async def test_conflicting_local_copy_cli_and_tui_do_not_show_arbitrary_history(
    tmp_path, fake_executable
):
    import tomli_w
    from textual.widgets import Static
    from typer.testing import CliRunner

    from sessions_manager.cli import app as cli
    from sessions_manager.messages import explain
    from sessions_manager.ui.app import SessionsApp

    with local_copies(tmp_path, fake_executable, "body") as (cfg, catalog, root, first, second):
        before = [p.read_bytes() for p in (first, second)]
        refresh(cfg, catalog)
        uid = catalog.sessions()[0].display_id
        cfg.config_path.write_text(
            tomli_w.dumps(
                {
                    "discovery_roots_mode": "replace",
                    "sources": [
                        {
                            "provider": "claude",
                            "path": str(root.path),
                            "executable": str(fake_executable),
                            "executable_version": "synthetic",
                            "resume_context": "native",
                        }
                    ],
                }
            )
        )
        base = [
            "--config",
            str(cfg.config_path),
            "--data-dir",
            str(cfg.data_dir),
            "--format",
            "json",
        ]
        runner = CliRunner()
        shown = runner.invoke(cli, [*base, "show", uid])
        assert shown.exit_code == 0, shown.output
        assert json.loads(shown.stdout)["data"]["events"] == []
        searched = runner.invoke(cli, [*base, "list", "--query", "ALPHA"])
        assert searched.exit_code == 3 and not json.loads(searched.stdout)["data"]["items"]
        stats = runner.invoke(cli, [*base, "stats", "--session", uid])
        assert stats.exit_code == 0, stats.output
        assert json.loads(stats.stdout)["data"]["metrics"]["messages"]["value"] is None
        tui = SessionsApp(cfg, catalog)
        async with tui.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            rendered = " ".join(str(w.render()) for w in tui.screen.query(Static))
            assert "ALPHA" not in rendered and "BETA" not in rendered
            await pilot.press("escape", "d")
            await pilot.pause()
            assert explain("identity_conflict") in " ".join(
                str(w.render()) for w in tui.screen.query(Static)
            )
        assert [p.read_bytes() for p in (first, second)] == before
