import pytest
from textual.app import App

from sessions_manager.ui.screens import CleanupScreen


@pytest.mark.asyncio
async def test_default_claude_delete_and_restore_without_version_config(isolated, tmp_path):
    from sessions_manager.catalog import Catalog
    from sessions_manager.config import Config
    from sessions_manager.discovery import refresh
    from sessions_manager.models import SourceRoot
    from sessions_manager.ui.app import SessionsApp
    from sessions_manager.ui.screens import TrashScreen
    from tests.support.claude_factory import make
    from tests.support.cleanup_case import version_cli

    config, data = isolated
    binary = version_cli(tmp_path)
    root = SourceRoot.create("claude", tmp_path / "native", executable_path=binary)
    path = make(root.path)
    path.write_text(path.read_text().replace('"version": "2.1.263"', '"version": "2.1.211"', 1))
    neighbor = make(root.path, "neighbor", message_id="neighbor-answer")
    before, neighbor_before = path.read_bytes(), neighbor.read_bytes()
    cfg = Config(data, config, [root], "replace")
    cfg.prepare()
    with Catalog(data) as catalog:
        refresh(cfg, catalog)
        row = next(s for s in catalog.sessions() if s.native_id == "claude-one")
        assert row.capabilities["cleanup"].state == "supported"
        app = SessionsApp(cfg, catalog)
        async with app.run_test(size=(120, 40)) as pilot:
            table = app.query_one("#sessions")
            table.move_cursor(row=table.get_row_index(row.session_uid))
            await pilot.press("d")
            assert isinstance(app.screen, CleanupScreen)
            app.screen.query_one("#closed").value = True
            app.screen.query_one("#confirm").press()
            await pilot.pause()
            assert not path.exists() and neighbor.read_bytes() == neighbor_before
            await pilot.press("escape")
            # A new invocation has no configured/detected version yet.
            app.config = Config(
                data,
                config,
                [SourceRoot.create("claude", root.path, executable_path=binary)],
                "replace",
            )
            await pilot.press("t")
            assert isinstance(app.screen, TrashScreen)
            await pilot.press("r")
            assert isinstance(app.screen, CleanupScreen)
            app.screen.query_one("#confirm").press()
            await pilot.pause()
            assert path.read_bytes() == before
            assert neighbor.read_bytes() == neighbor_before


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


async def test_tui_retry_exposes_operation_without_trash_copy(tmp_path, monkeypatch):
    import pytest
    from textual.widgets import DataTable, Static

    from sessions_manager.ui.app import SessionsApp
    from tests.integration.test_cleanup_recovery import Crash
    from tests.support.cleanup_case import case

    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])
        actual = service._assert_current_bundle

        def crash(*args):
            raise Crash()

        monkeypatch.setattr(service, "_assert_current_bundle", crash)
        with pytest.raises(Crash):
            service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        monkeypatch.setattr(service, "_assert_current_bundle", actual)
        app = SessionsApp(service.config, service.catalog)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("t")
            await pilot.pause()
            table = app.screen.query_one("#trash-table", DataTable)
            assert table.row_count == 1
            await pilot.click("#retry")
            await pilot.pause()
            assert "same" in " ".join(str(w.render()).lower() for w in app.screen.query(Static))
            await pilot.click("#closed")
            await pilot.click("#confirm")
            await pilot.pause()
            assert not path.exists() and neighbor.exists()


async def test_failed_no_change_tui_offers_new_preview_and_separate_staging_purge(tmp_path):
    from sessions_manager.models import Failure
    from sessions_manager.ui.app import SessionsApp
    from sessions_manager.ui.screens import TrashScreen
    from tests.support.cleanup_case import case

    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])

        def fail(stage, target):
            if stage == "before_copy":
                raise Failure("insufficient_space", 6)

        service.fault = fail
        service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        app = SessionsApp(service.config, service.catalog)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("t")
            assert isinstance(app.screen, TrashScreen)
            assert app.screen.query_one("#retry").disabled
            assert app.screen.query_one("#restore").disabled
            assert not app.screen.query_one("#new-preview").disabled
            await pilot.click("#new-preview")
            assert isinstance(app.screen, CleanupScreen)
            assert app.screen.plan["action"] == "trash"
            assert app.screen.plan["targets"][0]["target_id"] == uid
            await pilot.press("escape")
            await pilot.press("t")
            await pilot.click("#purge")
            assert app.screen.plan["action"] == "purge"
            assert path.exists() and neighbor.exists()
            await pilot.click("#confirm")
            await pilot.pause()
            assert path.exists() and neighbor.exists()
