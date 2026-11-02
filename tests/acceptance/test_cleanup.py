import pytest
from textual.app import App

from sessions_manager.ui.screens import CleanupScreen


@pytest.mark.asyncio
async def test_destructive_modal_defaults_to_cancel():
    app = App()
    async with app.run_test() as pilot:
        app.push_screen(
            CleanupScreen(
                {
                    "action": "purge",
                    "targets": ["exact-id"],
                    "known_bytes": 10,
                    "bytes_complete": True,
                },
                lambda _: None,
            )
        )
        await pilot.pause()
        assert app.screen.focused.id == "cancel"
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, CleanupScreen)
