import threading

import pytest
from textual.widgets import DataTable, Static

from sessions_manager.catalog import Catalog
from sessions_manager.config import Config
from sessions_manager.discovery import refresh
from sessions_manager.models import Session, SourceRoot
from sessions_manager.ui.app import SessionsApp
from sessions_manager.ui.screens import DetailsScreen, TextScreen
from tests.support.claude_factory import make


@pytest.fixture
def many(tmp_path):
    root = SourceRoot.create("claude", tmp_path / "native")
    root.path.mkdir()
    cfg = Config(tmp_path / "data", tmp_path / "config", [root], "replace")
    cfg.prepare()
    rows = [
        Session.build(root, f"row-{i:03}", root.path / str(i), title=f"row-{i:03}")
        for i in range(225)
    ]
    with Catalog(cfg.data_dir) as catalog:
        catalog.publish(root, rows, complete=True)
        app = SessionsApp(cfg, catalog)
        app.refresh_schedule.clock = lambda: 0.0
        app.refresh_schedule.next_poll = 5
        app.filters = {"sort": "title"}
        yield app, catalog, root, rows


async def test_pages_load_once_on_keyboard_and_mouse_scroll_and_keep_batch(many):
    app, catalog, _, rows = many
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.query_one("#sessions", DataTable)
        assert table.row_count == 100
        app.batch_selection = {rows[220].session_uid}
        table.move_cursor(row=79)
        await pilot.press("down")
        await pilot.pause()
        assert table.row_count == 200
        assert rows[220].session_uid in app.batch_selection
        table.scroll_end(animate=False)
        await pilot.pause()
        assert table.row_count == 225
        assert len({key.value for key in table.rows}) == 225
        assert "Loaded 225 of 225" in str(app.query_one("#status", Static).content)
        app.apply_filters({"project": "no match"})
        assert table.row_count == 0 and app.batch_selection == set()


async def test_refresh_preserves_uid_outside_first_page_and_filter_resets(many):
    from dataclasses import replace

    app, catalog, root, rows = many
    async with app.run_test() as pilot:
        table = app.query_one("#sessions", DataTable)
        selected = app.selected_uid()
        changed = [replace(s, title="zz-last") if s.session_uid == selected else s for s in rows]
        catalog.publish(root, changed, complete=True)
        app.reload_rows()
        assert app.selected_uid() == selected and table.row_count == 25
        # Earlier pages stay reachable after the selected identity moves far away.
        table.move_cursor(row=1)
        await pilot.press("up")
        await pilot.pause()
        assert table.row_count == 125
        app.apply_filters({"sort": "title", "model": "absent"})
        assert table.row_count == 0
        app.apply_filters({"sort": "title"})
        assert table.row_count == 100
        await pilot.pause()


@pytest.fixture
def live(tmp_path):
    root = SourceRoot.create("claude", tmp_path / "native")
    path = make(root.path)
    cfg = Config(tmp_path / "data", tmp_path / "config", [root], "replace")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        refresh(cfg, catalog)
        app = SessionsApp(cfg, catalog)
        now = [0.0]
        app.refresh_schedule.clock = lambda: now[0]
        app.refresh_schedule.next_poll = 5
        yield app, catalog, root, path, now


async def cycle(app, now, time):
    now[0] = time
    app.auto_tick()
    await app.workers.wait_for_complete()


async def test_auto_creation_change_removal_toggle_and_unchanged_history(live, monkeypatch):
    from sessions_manager.sources.claude import Adapter

    app, catalog, root, path, now = live
    reads = []
    original = Adapter.read_history
    monkeypatch.setattr(
        Adapter, "read_history", lambda self, s: (reads.append(s.native_id), original(self, s))[1]
    )
    async with app.run_test() as pilot:
        await cycle(app, now, 5)
        assert reads == []
        make(root.path, "new")
        await cycle(app, now, 10)
        assert app.query_one("#sessions").row_count == 2 and reads == ["new"]
        path.write_text(path.read_text().replace("Synthetic Claude question", "changed question"))
        await cycle(app, now, 15)
        assert (
            next(s for s in catalog.sessions() if s.native_id == "claude-one").preview
            == "changed question"
        )
        path.unlink()
        await cycle(app, now, 20)
        assert app.query_one("#sessions").row_count == 1
        await pilot.click("#auto-refresh")
        assert not app.auto_enabled
        make(root.path, "disabled")
        await cycle(app, now, 25)
        assert app.query_one("#sessions").row_count == 1
        await pilot.press("f5")
        await app.workers.wait_for_complete()
        assert app.query_one("#sessions").row_count == 2


async def test_auto_defers_publication_and_keeps_open_details_snapshot(live):
    app, catalog, root, path, now = live
    async with app.run_test() as pilot:
        await cycle(app, now, 5)
        await pilot.press("enter")
        assert isinstance(app.screen, DetailsScreen)
        before = [dict(r) for r in catalog.root_states()]
        path.write_text(path.read_text().replace("Synthetic Claude question", "new detail body"))
        await cycle(app, now, 10)
        assert catalog.root_states() == before
        assert "new detail body" not in " ".join(str(w.render()) for w in app.screen.query(Static))
        path.write_text(path.read_text().replace("new detail body", "changed again during dialog"))
        await cycle(app, now, 15)
        await pilot.press("escape")
        app.auto_tick()
        assert catalog.sessions()[0].preview == "new detail body"
        await cycle(app, now, 20)
        assert catalog.sessions()[0].preview == "changed again during dialog"
        await pilot.press("enter")
        assert isinstance(app.screen, DetailsScreen)


async def test_source_error_preserves_cache_and_retries_at_thirty_seconds(live, monkeypatch):
    from sessions_manager.sources.claude import Adapter

    app, catalog, root, path, now = live
    async with app.run_test():
        await cycle(app, now, 5)
        original = Adapter.discover
        calls = []

        def failed(self):
            calls.append(True)
            raise OSError("private marker")

        monkeypatch.setattr(Adapter, "discover", failed)
        path.write_text(path.read_text() + "\n")
        await cycle(app, now, 10)
        assert app.query_one("#sessions").row_count == 1
        assert "incomplete" in str(app.query_one("#status", Static).content).lower()
        count = len(calls)
        await cycle(app, now, 39)
        assert len(calls) == count
        monkeypatch.setattr(Adapter, "discover", original)
        await cycle(app, now, 40)
        assert catalog.root_states()[0]["state"] == "complete"


async def test_history_reader_error_preserves_events_and_retries_without_new_stat(
    live, monkeypatch
):
    from sessions_manager.sources.claude import Adapter

    app, catalog, _, path, now = live
    async with app.run_test():
        await cycle(app, now, 5)
        uid = app.selected_uid()
        events = catalog.events(uid)
        original = Adapter.read_history

        def failed(self, session):
            raise OSError("synthetic reader error")

        monkeypatch.setattr(Adapter, "read_history", failed)
        path.write_text(path.read_text().replace("Synthetic Claude question", "updated history"))
        await cycle(app, now, 10)
        assert catalog.events(uid) == events
        assert "incomplete" in app.last_refresh
        monkeypatch.setattr(Adapter, "read_history", original)
        await cycle(app, now, 39)
        assert catalog.get(uid).history_state == "partial"
        await cycle(app, now, 40)
        assert catalog.get(uid).history_state == "complete"
        assert catalog.events(uid)[0]["text"] == "updated history"


async def test_open_waits_for_reader_and_revalidates_original_uid(live, monkeypatch):
    from sessions_manager.sources.claude import Adapter

    app, catalog, root, path, now = live
    entered, release = threading.Event(), threading.Event()
    original = Adapter.discover

    def blocked(self):
        if getattr(self, "metadata_only", False):
            entered.set()
            release.wait(5)
        return original(self)

    async with app.run_test() as pilot:
        await cycle(app, now, 5)
        monkeypatch.setattr(Adapter, "discover", blocked)
        path.write_text(path.read_text().replace("Synthetic Claude question", "changed"))
        now[0] = 10
        app.auto_tick()
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await pilot.pause(0.01)
            assert entered.is_set()
            await pilot.press("o")
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert isinstance(app.screen, TextScreen)
            assert app.selected_uid() == catalog.sessions()[0].session_uid
        finally:
            release.set()


async def test_manual_requests_coalesce_and_changes_during_scan_are_seen(live, monkeypatch):
    from sessions_manager.sources.claude import Adapter

    app, catalog, root, path, now = live
    entered, release = threading.Event(), threading.Event()
    original = Adapter.discover
    scans = []

    def blocked(self):
        if getattr(self, "metadata_only", False):
            entered.set()
            release.wait(5)
        else:
            scans.append(True)
        return original(self)

    async with app.run_test() as pilot:
        await cycle(app, now, 5)
        monkeypatch.setattr(Adapter, "discover", blocked)
        path.write_text(path.read_text() + "\n")
        now[0] = 10
        app.auto_tick()
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await pilot.pause(0.01)
            assert entered.is_set()
            for _ in range(10):
                app.action_refresh()
            make(root.path, "during-scan")
            release.set()
            await app.workers.wait_for_complete()
            assert len(scans) == 1
            app.auto_tick()
            await app.workers.wait_for_complete()
            assert len(scans) == 2 and not app._pending_refresh
            assert app.query_one("#sessions").row_count == 2
            # Automatic observation compares against the stamp taken before the scan.
            await cycle(app, now, 15)
            assert len(scans) == 3
            await cycle(app, now, 20)
            assert len(scans) == 3
        finally:
            release.set()


@pytest.mark.parametrize("cancel_worker", [False, True])
async def test_shutdown_joins_active_readers(live, monkeypatch, cancel_worker):
    import asyncio

    from sessions_manager.sources.claude import Adapter

    app, catalog, root, path, now = live
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = Adapter.discover

    def blocked(self):
        entered.set()
        release.wait(5)
        try:
            return original(self)
        finally:
            finished.set()

    async with app.run_test() as pilot:
        monkeypatch.setattr(Adapter, "discover", blocked)
        app.action_refresh()
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await pilot.pause(0.01)
            assert entered.is_set()
            if cancel_worker:
                app.workers.cancel_all()
            quit_task = asyncio.create_task(app.action_quit())
            await asyncio.sleep(0)
            assert not quit_task.done()
            release.set()
            await quit_task
            assert finished.is_set() and not app.scanning
            assert not app._pending_refresh and not app._deferred_results
        finally:
            release.set()


async def test_page_revision_change_reloads_without_duplicates(many):
    from dataclasses import replace

    app, catalog, root, rows = many
    async with app.run_test() as pilot:
        table = app.query_one("#sessions", DataTable)
        selected = app.selected_uid()
        # Another manager writes between scrolling and the request for page two.
        catalog.publish(
            root,
            [replace(s, title="aa-new") if i == 180 else s for i, s in enumerate(rows)],
            complete=True,
        )
        table.move_cursor(row=85)
        await pilot.press("down")
        await pilot.pause()
        assert table.row_count == 200
        expected = catalog.query_page(app_spec(app), 200, 0)
        assert list(key.value for key in table.rows) == [s.session_uid for s in expected.rows]
        assert selected in table.rows


async def test_quit_before_scheduled_scan_starts(live, monkeypatch):
    import asyncio

    app, _, _, _, _ = live
    from sessions_manager.sources.claude import Adapter

    calls = []
    original = Adapter.discover
    monkeypatch.setattr(Adapter, "discover", lambda self: (calls.append(True), original(self))[1])
    async with app.run_test():
        app.action_refresh()
        await asyncio.wait_for(app.action_quit(), 2)
        assert not app.scanning
        assert calls == []


async def test_cancelled_stat_worker_is_joined(live, monkeypatch):
    import asyncio

    from sessions_manager.watch import observe_roots

    app, _, _, _, now = live
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocked(roots):
        entered.set()
        release.wait(5)
        try:
            return observe_roots(roots)
        finally:
            finished.set()

    monkeypatch.setattr("sessions_manager.ui.app.observe_roots", blocked)
    async with app.run_test() as pilot:
        now[0] = 5
        app.auto_tick()
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await pilot.pause(0.01)
            assert entered.is_set()
            app.workers.cancel_all()
            await asyncio.sleep(0)
            assert not finished.is_set()
            release.set()
            await app.action_quit()
            assert finished.is_set() and not app.scanning
        finally:
            release.set()


def app_spec(app):
    from sessions_manager.search import QuerySpec

    return QuerySpec(query=app.query, scope=app.scope, **app.filters)


async def test_batch_confirmation_keeps_original_off_page_ids(many, monkeypatch):
    from sessions_manager.ui.screens import CleanupScreen

    app, catalog, _, rows = many
    calls = []

    class Service:
        def __init__(self, config, catalog):
            pass

        def preview(self, action, ids):
            calls.append(("preview", list(ids)))
            return {"action": action, "confirmation_token": "synthetic"}

        def commit(self, action, ids, token, **kwargs):
            calls.append(("commit", list(ids)))
            return {"items": []}

    monkeypatch.setattr("sessions_manager.cleanup.CleanupService", Service)
    async with app.run_test() as pilot:
        chosen = {rows[0].session_uid, rows[220].session_uid}
        app.batch_selection = set(chosen)
        app.reload_rows()
        await pilot.press("d")
        assert isinstance(app.screen, CleanupScreen)
        app.batch_selection = {rows[10].session_uid}
        app.query_one("#sessions", DataTable).move_cursor(row=10)
        await pilot.click("#confirm")
        assert calls == [("preview", sorted(chosen)), ("commit", sorted(chosen))]


@pytest.mark.parametrize("queued_scroll", [False, True])
async def test_filter_change_cancels_queued_page_request(many, queued_scroll):
    app, _, _, _ = many
    async with app.run_test() as pilot:
        await pilot.pause()
        if queued_scroll:
            app.query_one("#sessions").scroll_end(animate=False)
        else:
            app.request_more()
        app.apply_filters({"scope": "all", "sort": "title"})
        await pilot.pause()
        assert app.query_one("#sessions").row_count == 100


async def test_disappearing_anchor_page_falls_back_to_surviving_rows(many):
    from dataclasses import replace

    app, catalog, root, rows = many
    async with app.run_test() as pilot:
        selected = app.selected_uid()
        catalog.publish(
            root,
            [replace(s, title="zz-last") if s.session_uid == selected else s for s in rows],
            complete=True,
        )
        app.reload_rows()
        assert app.selected_uid() == selected
        catalog.publish(root, rows[1:40], complete=True)
        app.reload_rows()
        assert app.query_one("#sessions").row_count == 39
        assert app.selected_uid() != selected
        await pilot.pause()


async def test_auto_refreshes_all_alias_roots_with_source_scope_only(tmp_path):
    from tests.support.grok_factory import make as grok

    roots = [SourceRoot.create("claude", tmp_path / name) for name in ("a", "alias")]
    other = SourceRoot.create("grok", tmp_path / "grok")
    project = tmp_path / "shared-project"
    paths = [make(r.path, "shared", cwd=project) for r in roots]
    outside = make(roots[0].path, "outside", cwd=tmp_path / "elsewhere")
    grok(other.path)
    cfg = Config(tmp_path / "manager", tmp_path / "config", [*roots, other], "replace")
    cfg.prepare()
    with Catalog(cfg.data_dir) as catalog:
        refresh(cfg, catalog)
        app = SessionsApp(cfg, catalog)
        now = [0.0]
        app.refresh_schedule.clock = lambda: now[0]
        app.refresh_schedule.next_poll = 5
        app.filters = {"providers": ["claude"], "project": "shared-project"}
        async with app.run_test() as pilot:
            await cycle(app, now, 5)
            before = {r["root_id"]: r["as_of"] for r in catalog.root_states()}
            await pilot.press("enter")
            paths[0].unlink()
            outside.write_text(
                outside.read_text().replace("Synthetic Claude question", "outside-filter")
            )
            await cycle(app, now, 10)
            assert {r["root_id"]: r["as_of"] for r in catalog.root_states()} == before
            await pilot.press("escape")
            app.auto_tick()
            after = {r["root_id"]: r["as_of"] for r in catalog.root_states()}
            assert all(after[r.root_id] != before[r.root_id] for r in roots)
            assert after[other.root_id] == before[other.root_id]
            shared = next(s for s in catalog.sessions() if s.native_id == "shared")
            assert shared.history_state == "complete" and shared.root_id == roots[1].root_id
            assert (
                next(s for s in catalog.sessions() if s.native_id == "outside").preview
                == "outside-filter"
            )
            assert app.query_one("#sessions").row_count == 1
