import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.models import SourceRoot
from sessions_manager.ui.app import SessionsApp
from tests.support.claude_factory import make


@pytest.mark.asyncio
async def test_history_screen_literal(isolated, tmp_path):
    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    make(root.path, text="[red]literal[/red] \x1b]0;bad\x07 \u202eend")
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        app = SessionsApp(cfg, catalog)
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            from textual.widgets import Static

            text = str(app.screen.query_one(Static).render())
            assert "[red]literal[/red]" in text
            assert "\x1b" not in text
            assert "total_tokens: 20" in text


@pytest.mark.asyncio
async def test_history_pagination_in_tui(isolated, tmp_path):
    from tests.support.claude_factory import append

    config, data = isolated
    root = SourceRoot.create("claude", tmp_path / "native")
    path = make(root.path)
    for index in range(201):
        append(
            path,
            {
                "type": "user",
                "uuid": f"page-{index}",
                "sessionId": "claude-one",
                "version": "2.1.263",
                "message": {"content": f"page text {index:03d}"},
            },
        )
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        app = SessionsApp(cfg, catalog)
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.click("#next-page")
            await pilot.pause()
            from textual.widgets import Static

            assert "page text 100" in str(app.screen.query_one("#history-content", Static).render())
