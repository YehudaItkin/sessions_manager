import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.models import SourceRoot
from sessions_manager.ui.app import SessionsApp
from tests.support.claude_factory import make


@pytest.mark.asyncio
async def test_refresh_and_open_have_distinct_keys(isolated, tmp_path, monkeypatch):
    from sessions_manager.ui.screens import ResumeScreen

    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    make(root.path)
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        app = SessionsApp(cfg, catalog)
        calls = []
        monkeypatch.setattr(app, "action_refresh", lambda: calls.append("refresh"))
        async with app.run_test() as pilot:
            await pilot.press("f5")
            assert calls == ["refresh"]
            await pilot.press("o")
            assert isinstance(app.screen, ResumeScreen)


@pytest.mark.asyncio
async def test_r_restores_only_selected_trash_entry():
    from textual.app import App

    from sessions_manager.ui.screens import TrashScreen

    chosen = []
    app = App()
    async with app.run_test() as pilot:
        app.push_screen(
            TrashScreen(
                [
                    {
                        "trash_id": "t-example",
                        "session_id": "s-example",
                        "state": "trashed",
                        "available_actions": ["restore", "purge"],
                    }
                ],
                lambda action, ids: chosen.append((action, ids)),
            )
        )
        await pilot.pause()
        await pilot.press("r")
        assert chosen == [("restore", ["t-example"])]


@pytest.mark.asyncio
async def test_tui_ids_and_stable_selection(isolated, tmp_path):
    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    make(root.path)
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        app = SessionsApp(cfg, catalog)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#sessions")
            assert table.row_count == 1
            assert table.ordered_columns[0].label.plain == "Manager ID"
            assert table.ordered_columns[1].label.plain == "Native ID"
            uid = app.selected_uid()
            app.reload_rows()
            assert app.selected_uid() == uid
            await pilot.press("f")
            from textual.widgets import Select

            app.screen.query_one("#sort-filter", Select).value = "updated"
            app.screen.query_one("#order-filter", Select).value = "asc"
            await pilot.click("#apply")
            assert app.filters["sort"] == "updated"
            assert app.filters["order"] == "asc"


@pytest.mark.asyncio
async def test_filter_keeps_full_refresh_scope(isolated, tmp_path):
    from tests.support.grok_factory import make as grok

    config, data = isolated
    a = SourceRoot.create("claude", tmp_path / "claude")
    c = SourceRoot.create("grok", tmp_path / "grok")
    make(a.path, "A", cwd=tmp_path / "project A")
    b = make(a.path, "B", cwd=tmp_path / "project B")
    grok(c.path, "C")
    cfg = Config(data, config, [a, c], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        original = next(s.current_generation for s in catalog.sessions() if s.native_id == "C")
        app = SessionsApp(cfg, catalog)
        async with app.run_test():
            app.apply_filters({"providers": ["claude"], "project": "project A"})
            assert app.query_one("#sessions").row_count == 1
            b.write_text(
                b.read_text().replace("Synthetic Claude question", "changed outside filter")
            )
            await app.refresh_catalog()
            assert (
                next(s for s in catalog.sessions() if s.native_id == "B").preview
                == "changed outside filter"
            )
            assert (
                next(s.current_generation for s in catalog.sessions() if s.native_id == "C")
                == original
            )
