import json
import pickle
import shutil

import pytest
from typer.testing import CliRunner

from sessions_manager.catalog import Catalog
from sessions_manager.cli import app
from sessions_manager.config import Config
from sessions_manager.discovery import (
    prepare_scan,
    publish_scan,
    scan_for_transport,
    scan_metadata,
    scan_root,
)
from sessions_manager.models import SourceRoot
from sessions_manager.search import QuerySpec
from tests.support.claude_factory import make


@pytest.mark.parametrize("cross_root", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_alias_activity_survives_publication_warm_cache_and_transport(
    tmp_path, fake_executable, monkeypatch, cross_root, reverse
):
    roots = [
        SourceRoot.create(
            "claude",
            tmp_path / name,
            executable_path=fake_executable,
            executable_version="synthetic",
            resume_context="native",
        )
        for name in ("a", "b")
    ]
    first = make(roots[0].path, "same", cwd=tmp_path / "project")
    if cross_root:
        second = make(roots[1].path, "same", cwd=tmp_path / "project")
    else:
        roots = roots[:1]
        second = roots[0].path / "projects" / "zz-copy" / first.name
        second.parent.mkdir()
        shutil.copyfile(first, second)
    records = roots[0].path / "sessions"
    records.mkdir()
    (records / "live.json").write_text(
        json.dumps(
            {"session_id": "same", "cwd": str(tmp_path / "project"), "pid": 123, "pid_start": 100}
        )
    )
    monkeypatch.setattr(
        "sessions_manager.activity.process_info",
        lambda pid: {"pid_start": 100, "executable": str(fake_executable.resolve())},
    )
    cfg = Config(tmp_path / "manager", tmp_path / "config", roots, "replace")
    cfg.prepare()
    original = [p.read_bytes() for p in (first, second)]
    with Catalog(cfg.data_dir) as catalog:
        for cycle in range(2):
            _, args = prepare_scan(cfg, catalog)
            for i in range(len(roots)):
                publish_scan(catalog, roots[i], scan_metadata(args[i]))
            indices = list(range(len(roots)))
            if reverse:
                indices.reverse()
            for i in indices:
                result = scan_for_transport(args[i]) if cycle else scan_root(args[i])
                if reverse:
                    result.sessions.reverse()
                publish_scan(catalog, roots[i], pickle.loads(pickle.dumps(result)))
            rows = QuerySpec(scope="all", activity="active").filter(catalog.sessions())
            assert len(rows) == 1
            session = rows[0]
            assert session.activity_evidence["status"] == "active"
            assert session.capabilities["cleanup"].state != "supported"
            if cycle == 0:
                uid = session.session_uid
                catalog.hide([uid], True)
            assert session.session_uid == uid
        import sessions_manager.cli as cli

        monkeypatch.setattr(cli, "runtime", lambda *args, **kwargs: (cfg, catalog))
        monkeypatch.setattr(catalog, "close", lambda: None)
        response = CliRunner().invoke(
            app, ["--format", "json", "list", "--scope", "all", "--activity", "active"]
        )
        assert response.exit_code == 0, response.output
        assert json.loads(response.stdout)["data"]["items"][0]["session_uid"] == uid
        from sessions_manager.ui.app import SessionsApp

        async def pilot_check():
            tui = SessionsApp(cfg, catalog)
            async with tui.run_test(size=(80, 24)) as pilot:
                tui.scope = "all"
                tui.filters = {"activity": "active"}
                tui.reload_rows()
                assert tui.selected_uid() == uid
                await pilot.press("space")
                tui.reload_rows()
                assert tui.batch_selection == {uid}

        import asyncio

        asyncio.run(pilot_check())
        (records / "live.json").unlink()
        _, arguments = prepare_scan(cfg, catalog)
        assert catalog.get(uid).activity == "unknown"
        for i in range(len(roots)):
            publish_scan(catalog, roots[i], scan_metadata(arguments[i]))
            publish_scan(catalog, roots[i], scan_root(arguments[i]))
        assert catalog.get(uid).activity == "unknown"
        assert not QuerySpec(scope="all", activity="active").filter(catalog.sessions())
        assert [p.read_bytes() for p in (first, second)] == original
