from contextlib import contextmanager

import pytest
from textual.widgets import Button, DataTable, Input, Select, SelectionList, Static

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.models import SourceRoot
from sessions_manager.ui.app import SessionsApp
from sessions_manager.ui.screens import FiltersScreen
from tests.support.claude_factory import make
from tests.support.grok_factory import make as grok


@contextmanager
def case(isolated, tmp_path):
    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "claude")
    other = SourceRoot.create("grok", tmp_path / "grok")
    for native in ("Alpha", "zeta", "excluded"):
        path = make(root.path, native, cwd=tmp_path / "My Project")
        if native == "excluded":
            path.write_text(path.read_text().replace('"model": "synthetic"', '"model": "other"'))
    grok(other.path, "B", cwd=tmp_path / "My Project")
    cfg = Config(data, config, [root, other], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        yield SessionsApp(cfg, catalog), catalog


def native_rows(app, catalog):
    return [
        catalog.get(str(key.value)).native_id for key in app.query_one("#sessions", DataTable).rows
    ]


@pytest.mark.asyncio
async def test_visible_multisource_filter_sort_summary_reopen_and_reset(isolated, tmp_path):
    with case(isolated, tmp_path) as (app, catalog):
        async with app.run_test(size=(110, 32)) as pilot:
            assert app.query_one("#filter-sort", Button).display
            await pilot.click("#filter-sort")
            sources = app.screen.query_one("#source-filter", SelectionList)
            sources.deselect_all().select("claude").select("grok")
            app.screen.query_one("#model-filter", Input).value = "SYNTH"
            app.screen.query_one("#project-filter", Input).value = "my project"
            app.screen.query_one("#activity-filter", Select).value = "unknown"
            app.screen.query_one("#sort-filter", Select).value = "id"
            app.screen.query_one("#order-filter", Select).value = "desc"
            await pilot.click("#apply")
            assert native_rows(app, catalog) == ["zeta", "B", "Alpha"]
            summary = str(app.query_one("#selection-summary", Static).content)
            assert "Native ID" in summary and "↓" in summary and "SYNTH" in summary
            await pilot.press("f")
            assert set(app.screen.query_one("#source-filter", SelectionList).selected) == {
                "claude",
                "grok",
            }
            await pilot.press("escape")
            await pilot.click("#reset-view")
            assert app.filters == {} and app.scope == "visible"
            assert len(native_rows(app, catalog)) == 4


@pytest.mark.asyncio
async def test_header_click_toggles_order_without_changing_selected_identity(isolated, tmp_path):
    with case(isolated, tmp_path) as (app, catalog):
        async with app.run_test(size=(110, 32)) as pilot:
            table = app.query_one("#sessions", DataTable)
            ids = {s.native_id: s.session_uid for s in catalog.sessions()}
            table.move_cursor(row=table.get_row_index(ids["Alpha"]))
            app.batch_selection = {ids["Alpha"], ids["B"]}
            await pilot.click("#sessions", offset=(17, 0))
            assert native_rows(app, catalog) == ["Alpha", "B", "excluded", "zeta"]
            assert app.selected_uid() == ids["Alpha"]
            await pilot.click("#sessions", offset=(17, 0))
            assert native_rows(app, catalog) == ["zeta", "excluded", "B", "Alpha"]
            assert app.selected_uid() == ids["Alpha"]
            assert app.batch_selection == {ids["Alpha"], ids["B"]}
            app.apply_filters({"providers": ["grok"]})
            assert app.batch_selection == {ids["B"]}
            assert app.selected_ids() == [ids["B"]]


@pytest.mark.asyncio
async def test_invalid_draft_stays_editable_and_clear_restores_defaults(isolated, tmp_path):
    with case(isolated, tmp_path) as (app, catalog):
        async with app.run_test(size=(100, 28)) as pilot:
            await pilot.press("f")
            sources = app.screen.query_one("#source-filter", SelectionList)
            sources.deselect_all()
            await pilot.click("#apply")
            assert isinstance(app.screen, FiltersScreen)
            sources.select("claude")
            app.screen.query_one("#since-filter", Input).value = "2026-02-01"
            app.screen.query_one("#until-filter", Input).value = "2026-01-01"
            await pilot.click("#apply")
            assert isinstance(app.screen, FiltersScreen)
            assert app.filters == {}
            await pilot.click("#clear-filters")
            assert len(sources.selected) == 4
            assert app.screen.query_one("#since-filter", Input).value == ""
            assert app.screen.query_one("#order-filter", Select).value == "desc"
            await pilot.click("#apply")
            assert not isinstance(app.screen, FiltersScreen)
            assert len(native_rows(app, catalog)) == 4


@pytest.mark.asyncio
async def test_small_terminal_source_keyboard_and_escape_reset(isolated, tmp_path):
    with case(isolated, tmp_path) as (app, catalog):
        async with app.run_test(size=(80, 24)) as pilot:
            uid = app.selected_uid()
            app.batch_selection = {uid}
            app.query = "Synthetic"
            app.query_one("#query", Input).value = app.query
            app.reload_rows()
            await pilot.press("f")
            sources = app.screen.query_one("#source-filter", SelectionList)
            sources.focus()
            await pilot.press("space")
            assert len(sources.selected) == 3
            assert app.batch_selection == {uid}
            await pilot.click("#clear-filters")
            assert len(sources.selected) == 4
            await pilot.click("#cancel")
            assert app.query == "Synthetic"
            await pilot.press("escape")
            assert app.query == "" and app.query_one("#query", Input).value == ""


@pytest.mark.asyncio
async def test_enter_in_filter_input_does_not_submit_main_search(isolated, tmp_path):
    with case(isolated, tmp_path) as (app, catalog):
        async with app.run_test(size=(100, 28)) as pilot:
            await pilot.press("f")
            field = app.screen.query_one("#project-filter", Input)
            field.value = "draft project"
            field.focus()
            await pilot.press("enter")
            assert isinstance(app.screen, FiltersScreen)
            assert app.query == "" and app.filters == {}


@pytest.mark.asyncio
async def test_toolbar_stays_visible_with_many_rows_in_small_terminal(isolated, tmp_path):
    with case(isolated, tmp_path) as (app, catalog):
        for index in range(40):
            make(app.config.roots[0].path, f"extra-{index}")
        refresh(app.config, catalog)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            button = app.query_one("#filter-sort", Button)
            assert button.region.y >= 0 and button.region.bottom < 24
            await pilot.click("#filter-sort")
            assert isinstance(app.screen, FiltersScreen)
