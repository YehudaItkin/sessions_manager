import pytest
from textual.widgets import DataTable, Input, Static

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.models import SourceRoot
from sessions_manager.ui.app import SessionsApp
from sessions_manager.ui.screens import ResumeScreen
from tests.support.claude_factory import make


@pytest.mark.parametrize("terminal", ["current", "warp"])
@pytest.mark.parametrize("change", ["missing", "changed", "filtered", "guide", "cancel"])
async def test_open_dialog_keeps_original_session_across_refresh(
    tmp_path, fake_executable, monkeypatch, terminal, change
):
    from contextlib import nullcontext

    root = SourceRoot.create(
        "claude", tmp_path / "native", executable_path=fake_executable, resume_context="native"
    )
    project = tmp_path / "project"
    first = make(root.path, "first", cwd=project, text="ALPHA synthetic", message_id="first-api")
    make(root.path, "second", cwd=project, text="BETA synthetic", message_id="second-api")
    cfg = Config(tmp_path / "manager", tmp_path / "config", [root], "replace")
    cfg.prepare()
    launched = []

    def run(request, *args, **kwargs):
        launched.append((request.session_uid, request.cwd, request.target))
        return {"state": "child_exited"}

    monkeypatch.setattr("sessions_manager.launch.launch_current", run)
    monkeypatch.setattr("sessions_manager.warp.deliver", lambda catalog, request: run(request))
    with Catalog(cfg.data_dir) as catalog:
        refresh(cfg, catalog)
        original = next(s for s in catalog.sessions() if s.native_id == "first")
        app = SessionsApp(cfg, catalog)
        monkeypatch.setattr(app, "suspend", nullcontext)
        async with app.run_test(size=(80, 24)) as pilot:
            table = app.query_one("#sessions", DataTable)
            table.move_cursor(row=table.get_row_index(original.session_uid))
            await pilot.press("o")
            assert isinstance(app.screen, ResumeScreen)
            if change == "guide":
                app.screen.query_one("#cwd", Input).value = str(tmp_path / "missing-project")
                await pilot.click("#" + terminal)
                await pilot.pause()
                assert isinstance(app.screen, ResumeScreen) and app.screen.guide
                app.screen.query_one("#cwd", Input).value = str(project)
            if change == "missing":
                first.unlink()
            elif change == "changed":
                first.write_text(first.read_text().replace("ALPHA", "CHANGED"))
            await app.refresh_catalog()
            app.query = "BETA synthetic"
            app.reload_rows()
            assert app.selected_uid() != original.session_uid
            if change == "cancel":
                await pilot.press("escape")
            else:
                await pilot.click("#" + terminal)
            await pilot.pause()
            if change in ("missing", "changed", "cancel"):
                assert launched == []
            else:
                assert launched == [(original.session_uid, str(project), terminal)]
            if change in ("missing", "changed"):
                assert "changed" in " ".join(
                    str(w.render()).lower() for w in app.screen.query(Static)
                )
