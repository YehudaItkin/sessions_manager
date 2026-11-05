import pytest
from textual.widgets import Static

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.models import SourceRoot
from sessions_manager.ui.app import SessionsApp
from tests.support.cursor_factory import make


@pytest.mark.asyncio
async def test_stats_scope_is_explicit_and_includes_hidden_by_default(isolated, tmp_path):
    from textual.widgets import Select

    config, data = isolated
    root = SourceRoot.create("cursor", tmp_path / "native")
    make(root.path, "visible")
    make(root.path, "hidden")
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        catalog.hide([s.session_uid for s in catalog.sessions() if s.native_id == "hidden"], True)
        app = SessionsApp(cfg, catalog)
        async with app.run_test() as pilot:
            await pilot.press("s")
            await pilot.pause()
            scope = app.screen.query_one("#stats-scope", Select)
            assert scope.value == "all"
            assert '"selected_sessions": 2' in str(app.screen.query_one(Static).render())
            scope.value = "hidden"
            await pilot.pause()
            rendered = str(app.screen.query_one(Static).render())
            assert '"scope": "hidden"' in rendered
            assert '"selected_sessions": 1' in rendered
            await pilot.press("escape", "s")
            await pilot.pause()
            assert app.screen.query_one("#stats-scope", Select).value == "hidden"


@pytest.mark.asyncio
async def test_stats_ui_explains_unknown_cursor_tokens(isolated, tmp_path):
    config, data = isolated
    root = SourceRoot.create("cursor", tmp_path / "native")
    make(root.path)
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        app = SessionsApp(cfg, catalog)
        async with app.run_test() as pilot:
            await pilot.press("s")
            await pilot.pause()
            text = str(app.screen.query_one(Static).render())
            assert "selected_session_lifetimes" in text
            assert "not_recorded" in text
            from textual.widgets import Select

            app.screen.query_one("#stats-group", Select).value = "project"
            await pilot.pause()
            assert str(root.path / "project") in str(app.screen.query_one(Static).render())
