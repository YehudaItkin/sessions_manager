import pytest

from sessions_manager.ui.app import SessionsApp
from tests.integration.test_native_archive import archive_case


@pytest.mark.asyncio
async def test_archive_buttons_cancel_confirm_and_restore_preserve_prior_child(
    tmp_path, monkeypatch
):
    from textual.widgets import DataTable

    import sessions_manager.native_archive as native

    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        real = native.ArchiveService
        monkeypatch.setattr(
            native, "ArchiveService", lambda cfg, cat: real(cfg, cat, client_factory=client)
        )
        app = SessionsApp(service.config, service.catalog)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            table = app.query_one("#sessions", DataTable)
            table.move_cursor(row=table.get_row_index(uid[2:]))
            assert table.row_count == 3
            await pilot.click("#native-archive")
            await pilot.pause()
            await pilot.click("#cancel")
            assert calls == []
            await pilot.press("a")
            await pilot.pause()
            await pilot.click("#closed")
            await pilot.click("#confirm")
            await pilot.pause()
            await pilot.press("escape")
            assert flags()["parent"] == 1
            assert app.query_one("#sessions", DataTable).row_count == 1
            await pilot.click("#native-archives")
            await pilot.pause()
            archived = app.screen.query_one("#archive-table", DataTable)
            archived.move_cursor(row=archived.get_row_index("session:" + uid))
            await pilot.click("#unarchive")
            await pilot.pause()
            await pilot.click("#closed")
            await pilot.click("#confirm")
            await pilot.pause()
            assert flags() == dict(parent=0, child=0, prior=1, neighbor=0)


@pytest.mark.asyncio
async def test_refresh_started_while_archive_preview_is_open_blocks_confirmation(
    tmp_path, monkeypatch
):
    from textual.widgets import DataTable

    import sessions_manager.native_archive as native

    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        real = native.ArchiveService
        monkeypatch.setattr(
            native, "ArchiveService", lambda cfg, cat: real(cfg, cat, client_factory=client)
        )
        app = SessionsApp(service.config, service.catalog)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            table = app.query_one("#sessions", DataTable)
            table.move_cursor(row=table.get_row_index(uid[2:]))
            await pilot.press("a")
            await pilot.pause()
            app.scanning = True
            await pilot.click("#closed")
            await pilot.click("#confirm")
            await pilot.pause()
            app.scanning = False
            assert calls == [] and flags()["parent"] == 0


@pytest.mark.asyncio
async def test_archives_screen_retries_uncertain_native_operation(tmp_path, monkeypatch):
    from textual.widgets import DataTable

    import sessions_manager.native_archive as native
    from tests.integration.test_native_archive import perform

    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):
        behavior["lost"] = True
        operation = perform(service, "archive", uid)["operation_id"]
        real = native.ArchiveService
        monkeypatch.setattr(
            native, "ArchiveService", lambda cfg, cat: real(cfg, cat, client_factory=client)
        )
        app = SessionsApp(service.config, service.catalog)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("b")
            await pilot.pause()
            table = app.screen.query_one("#archive-table", DataTable)
            table.move_cursor(row=table.get_row_index("operation:" + operation))
            await pilot.click("#archive-retry")
            await pilot.pause()
            await pilot.click("#closed")
            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert flags() == dict(parent=1, child=1, prior=1, neighbor=0)
