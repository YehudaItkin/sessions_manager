import sqlite3

import pytest
from textual.widgets import Static

from sessions_manager.cleanup import CleanupService
from sessions_manager.models import Failure
from sessions_manager.ui.app import SessionsApp
from sessions_manager.ui.screens import DetailsScreen, TextScreen
from tests.support.cleanup_case import case


@pytest.mark.parametrize(
    "failure",
    [
        "constructor",
        "listing_io",
        "malformed_operation",
        "malformed_entry",
        "nested_entry",
        "missing",
        "denied",
    ],
)
async def test_trash_failure_preserves_journal_and_healthy_overview(tmp_path, monkeypatch, failure):
    from pathlib import Path

    with case(tmp_path) as (service, root, uid, path, neighbor):
        if failure not in ("constructor", "listing_io"):
            plan = service.preview("trash", [uid])
            result = service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
            trash = result["items"][0]["trash_id"]
            if failure == "malformed_operation":
                with service.catalog.writer() as db:
                    db.execute("UPDATE operation_items SET payload=?", ('{"PRIVATE-SENTINEL":',))
            elif failure == "malformed_entry":
                with service.catalog.writer() as db:
                    db.execute("UPDATE trash_entries SET payload=?", ('{"PRIVATE-SENTINEL":',))
            elif failure == "nested_entry":
                from tests.integration.test_cleanup_validation import corrupt_entry

                corrupt_entry(service, trash, "root")
            elif failure == "missing":
                (service.config.data_dir / "trash" / trash).rename(
                    service.config.data_dir / "retained-original-entry"
                )
            else:
                actual = Path.read_bytes

                def denied(target):
                    if target.name == "manifest.json":
                        raise PermissionError("PRIVATE-SENTINEL")
                    return actual(target)

                monkeypatch.setattr(Path, "read_bytes", denied)
        saved = [
            tuple(row)
            for row in service.catalog.connection.execute("SELECT * FROM operation_items")
        ]
        entries = [
            tuple(row) for row in service.catalog.connection.execute("SELECT * FROM trash_entries")
        ]
        neighbor_before = neighbor.read_bytes()
        if failure == "constructor":

            def unavailable(*args, **kwargs):
                raise Failure("unsafe_data_dir", 6)

            monkeypatch.setattr(CleanupService, "__init__", unavailable)
        elif failure == "listing_io":

            def unavailable(*args, **kwargs):
                raise sqlite3.OperationalError("PRIVATE-SENTINEL")

            monkeypatch.setattr(CleanupService, "trash_list", unavailable)
        app = SessionsApp(service.config, service.catalog)
        async with app.run_test(size=(80, 24)) as pilot:
            selected = app.selected_uid()
            await pilot.press("t")
            await pilot.pause()
            assert isinstance(app.screen, TextScreen)
            text = " ".join(str(w.render()) for w in app.screen.query(Static))
            assert "PRIVATE-SENTINEL" not in text
            await pilot.press("escape")
            assert app.selected_uid() == selected
            await pilot.press("enter")
            assert isinstance(app.screen, DetailsScreen)
            await pilot.press("escape")
            await app.refresh_catalog()
            assert app.selected_uid() == selected
        assert saved == [
            tuple(row)
            for row in service.catalog.connection.execute("SELECT * FROM operation_items")
        ]
        assert entries == [
            tuple(row) for row in service.catalog.connection.execute("SELECT * FROM trash_entries")
        ]
        assert neighbor.read_bytes() == neighbor_before


@pytest.mark.parametrize("stage", ["preview", "commit"])
async def test_trash_manifest_io_failure_after_listing_keeps_overview(tmp_path, monkeypatch, stage):
    from pathlib import Path

    from sessions_manager.ui.screens import CleanupScreen, TrashScreen

    with case(tmp_path) as (service, root, uid, path, neighbor):
        plan = service.preview("trash", [uid])
        service.commit("trash", [uid], plan["confirmation_token"], assert_closed=True)
        app = SessionsApp(service.config, service.catalog)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("t")
            assert isinstance(app.screen, TrashScreen)
            if stage == "commit":
                await pilot.press("r")
                assert isinstance(app.screen, CleanupScreen)
            original = Path.read_bytes

            def denied(target):
                if target.name == "manifest.json":
                    raise PermissionError("PRIVATE-SENTINEL")
                return original(target)

            monkeypatch.setattr(Path, "read_bytes", denied)
            if stage == "commit":
                app.screen.query_one("#confirm").press()
            else:
                await pilot.press("r")
            await pilot.pause()
            assert isinstance(app.screen, TextScreen)
            assert "PRIVATE-SENTINEL" not in " ".join(
                str(w.render()) for w in app.screen.query(Static)
            )
            await pilot.press("escape")
            assert app.selected_uid()
