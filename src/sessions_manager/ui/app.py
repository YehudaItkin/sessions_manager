import asyncio
import threading
from functools import partial

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from ..discovery import refresh
from ..messages import explain, human_data
from ..models import safe_text
from ..search import QuerySpec
from ..watch import RefreshSchedule, observe_roots
from .screens import TextScreen


class SessionTable(DataTable):
    restoring = False

    def on_key(self):
        self.call_after_refresh(self.check_cursor_page)

    def check_cursor_page(self):
        if self.cursor_row >= self.row_count - 20:
            self.post_message(self.NearEnd(self.row_count))
        elif self.cursor_row <= 20:
            self.post_message(self.NearEnd(self.row_count, before=True))

    def on_mouse_scroll_up(self):
        self.restoring = False

    def on_mouse_scroll_down(self):
        self.restoring = False

    class NearEnd(Message):
        def __init__(self, row_count, before=False):
            self.row_count, self.before = row_count, before
            super().__init__()

    def watch_scroll_y(self, old_value, new_value):
        super().watch_scroll_y(old_value, new_value)
        if self.restoring:
            return
        if new_value > old_value and new_value + self.size.height >= self.row_count - 20:
            self.post_message(self.NearEnd(self.row_count))
        elif new_value < old_value and new_value <= 20:
            self.post_message(self.NearEnd(self.row_count, before=True))


class SessionsApp(App):
    TITLE = "Sessions Manager"
    CSS = """
    #view-controls { height: 3; }
    #view-controls Button { margin-right: 1; }
    #auto-refresh { height: 3; }
    #selection-summary { height: auto; max-height: 3; }
    #sessions { height: 1fr; min-height: 0; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("f5", "refresh", "Refresh"),
        ("enter", "details", "Details"),
        ("/", "search", "Search"),
        ("f", "filters", "Filters"),
        ("escape", "reset", "Reset"),
        ("o", "resume", "Open"),
        ("h", "hide", "Hide/unhide"),
        ("d", "delete", "Move to trash"),
        ("t", "trash", "Trash"),
        ("a", "archive", "Archive Codex"),
        ("b", "archives", "Codex archives"),
        ("s", "statistics", "Statistics"),
        ("v", "scope", "Scope"),
        ("space", "toggle_selection", "Select"),
    ]

    def __init__(self, config, catalog):
        super().__init__()
        self.config, self.catalog = config, catalog
        self.source_status = []
        self.filters = {}
        self.scanning = False
        self.query = ""
        self.scope = "visible"
        self.stats_scope = "all"
        self.batch_selection = set()
        self.auto_enabled = True
        self.refresh_schedule = RefreshSchedule()
        self._limit = 100
        self._offset = 0
        self._total = 0
        self._revision = None
        self._view_filter = None
        self._view_generation = 0
        self._loading = False
        self._rendering = False
        self._pending_refresh = set()
        self._deferred_results = []
        self._deferred_roots = []
        self._scan_done = asyncio.Event()
        self._scan_done.set()
        self._cancel_scan = threading.Event()
        self._scan_task = None
        self._actions_paused = False
        self._action_waiting = False
        self._stopping_refresh = False
        self.last_refresh = "cached"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Cached catalog; F5 refreshes configured roots", id="status", markup=False)
        with Horizontal(id="view-controls"):
            yield Button("Filters / sort (f)", id="filter-sort")
            yield Button("Reset all (Esc)", id="reset-view")
            yield Button("Archive (a)", id="native-archive")
            yield Button("Archives (b)", id="native-archives")
        yield Button("Auto refresh: on", id="auto-refresh")
        yield Static("", id="selection-summary", markup=False)
        yield Input(placeholder="Literal search; Enter applies, Escape resets", id="query")
        yield SessionTable(id="sessions", cursor_type="row")
        yield Footer()

    def on_mount(self):
        table = self.query_one("#sessions", DataTable)
        for label, width, key in [
            ("Manager ID", 12, "manager-id"),
            ("Native ID", 22, "id"),
            ("Source", 7, "source"),
            ("Title / preview", 28, "title"),
            ("Project", 26, "project"),
            ("Created", 17, "created"),
            ("Last activity", 17, "updated"),
            ("Activity", 9, "activity"),
            ("Actions", 24, "actions"),
        ]:
            table.add_column(label, width=width, key=key)
        self.reload_rows()
        table.focus()
        self.set_interval(0.25, self.auto_tick)
        if not self.catalog.root_states() or not self.catalog.index_valid:
            self.action_refresh()

    def selected_uid(self):
        table = self.query_one("#sessions", DataTable)
        if table.row_count:
            return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        return None

    def reload_rows(self):
        table = self.query_one("#sessions", DataTable)
        previous = self.selected_uid()
        spec = QuerySpec(query=self.query, scope=self.scope, **self.filters)
        selection = spec.selection()
        reset = selection != self._view_filter
        self._view_filter = selection
        scroll, cursor = float(table.scroll_y), table.cursor_row
        if reset:
            self._limit, previous, scroll = 100, None, 0
            self._offset = 0
            self._view_generation += 1
            self._loading = False
        elif previous:
            position = self.catalog.query_position(spec, previous)
            if position is not None and not self._offset <= position < self._offset + self._limit:
                self._offset = (position // 100) * 100
        page = self.catalog.query_page(spec, self._limit, self._offset)
        if not page.rows and page.total and self._offset >= page.total:
            self._offset = ((page.total - 1) // 100) * 100
            page = self.catalog.query_page(spec, self._limit, self._offset)
        self._total, self._revision = page.total, page.revision
        self.batch_selection = self.catalog.matching_selection(spec, self.batch_selection)
        self.query_one("#selection-summary", Static).update(safe_text(spec.describe()))
        self._rendering = True
        table.restoring = True
        table.clear()
        self._append_rows(page.rows)
        if previous in table.rows:
            index = table.get_row_index(previous)
            table.move_cursor(row=index, scroll=False)
            if scroll <= cursor < scroll + table.size.height:
                scroll += index - cursor
        elif table.row_count:
            table.move_cursor(
                row=min(cursor, table.row_count - 1) if not reset else 0, scroll=False
            )
        table.scroll_to(y=max(0, scroll), animate=False, force=True)
        self._rendering = False
        table.call_after_refresh(setattr, table, "restoring", False)
        self.update_status()

    def _append_rows(self, rows):
        from rich.text import Text

        from ..models import display_session_time

        table = self.query_one("#sessions", DataTable)
        handles = self.catalog.handles()
        for s in rows:
            match = self.catalog.match_context(s.session_uid, self.query) if self.query else None
            preview = f"{match['field']}: {match['text']}" if match else s.title or s.preview
            table.add_row(
                handles[s.session_uid],
                Text(safe_text(s.native_id), overflow="ellipsis", no_wrap=True),
                s.provider,
                Text(("* " if s.session_uid in self.batch_selection else "") + safe_text(preview)),
                safe_text(s.cwd),
                display_session_time(s, "created_at"),
                display_session_time(s, "last_activity_at"),
                s.activity,
                " ".join(
                    key
                    for key in ("history", "resume", "cleanup", "usage", "archive")
                    if s.capabilities[key].state == "supported"
                ),
                key=s.session_uid,
            )

    def update_status(self):
        import json

        from ..models import display_time
        from ..search import local_zone

        states = self.catalog.root_states()
        health = ", ".join(json.loads(r["payload"])["provider"] + ":" + r["state"] for r in states)
        incomplete = bool(self.refresh_schedule.retry_at) or any(
            r["state"] != "complete" for r in states
        )
        known = [r["as_of"] for r in states if r["as_of"] is not None]
        hidden = self.catalog.connection.execute(
            "SELECT count(*) FROM sessions WHERE hidden=1"
        ).fetchone()[0]
        trash = self.catalog.connection.execute(
            "SELECT count(*) FROM sessions WHERE presence='trashed'"
        ).fetchone()[0]
        self.query_one("#status", Static).update(
            f"Loaded {self.query_one('#sessions', DataTable).row_count} of {self._total}"
            f"{f' | From row {self._offset + 1}' if self._offset else ''}"
            f"{' | Loading…' if self._loading else ''} | {self.scope}; {len(self.batch_selection)} selected; hidden {hidden}; trash {trash}"
            f"{' | Incomplete source data' if incomplete else ''}"
            f" | Last refresh: {self.last_refresh} | cached {display_time(min(known) if known else None)} ({local_zone()}) | {health or 'No source roots; use sources add'}"
        )

    def on_session_table_near_end(self, event: SessionTable.NearEnd):
        if self.is_running and not self._stopping_refresh:
            table = self.query_one("#sessions", DataTable)
            if event.row_count == table.row_count:
                self.request_more(before=event.before)

    def request_more(self, *, before=False):
        if not self.is_running or self._stopping_refresh:
            return
        table = self.query_one("#sessions", DataTable)
        exhausted = self._offset == 0 if before else self._offset + table.row_count >= self._total
        if self._rendering or table.restoring or self._loading or exhausted:
            return
        self._loading = True
        self.update_status()
        self.call_later(self.load_more, before=before, generation=self._view_generation)

    def load_more(self, *, before=False, generation=None):
        if self._stopping_refresh or not self.is_running:
            return
        if generation is not None and generation != self._view_generation:
            return
        try:
            spec = QuerySpec(query=self.query, scope=self.scope, **self.filters)
            table = self.query_one("#sessions", DataTable)
            if before:
                self._limit += min(100, self._offset)
                self._offset = max(0, self._offset - 100)
                self.reload_rows()
                return
            offset = self._offset + table.row_count
            page = self.catalog.query_page(spec, 100, offset)
            self._limit = table.row_count + 100
            if page.revision != self._revision:
                self.reload_rows()
            else:
                self._append_rows(page.rows)
                self._total = page.total
        finally:
            self._loading = False
            self.update_status()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "filter-sort":
            self.action_filters()
        elif event.button.id == "reset-view":
            self.action_reset()
        elif event.button.id == "native-archive":
            self.action_archive()
        elif event.button.id == "native-archives":
            self.action_archives()
        elif event.button.id == "auto-refresh":
            self.auto_enabled = not self.auto_enabled
            event.button.label = f"Auto refresh: {'on' if self.auto_enabled else 'off'}"
            self.refresh_schedule.next_poll = self.refresh_schedule.clock() + 5

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected):
        if event.data_table.id != "sessions" or event.column_key.value == "actions":
            return
        from ..search import QuerySpec

        field = event.column_key.value
        current, order = QuerySpec(**self.filters).sorting()
        self.filters["sort"] = field
        self.filters["order"] = (
            ("asc" if order == "desc" else "desc")
            if current == field
            else QuerySpec(sort=field).sorting()[1]
        )
        self.reload_rows()

    def action_refresh(self):
        self.request_refresh()

    def request_refresh(self, providers=None, *, automatic=False):
        providers = set(
            providers
            or self.filters.get("providers")
            or [r.provider for r in self.config.roots if r.enabled]
        )
        if self._stopping_refresh:
            return
        if self.scanning or self._actions_paused:
            if not automatic:
                self._pending_refresh.update(providers)
            return
        self.scanning = True
        self._scan_done.clear()
        self.run_worker(
            partial(self.refresh_catalog, providers=providers, automatic=automatic), group="scan"
        )

    def auto_tick(self):
        if self._stopping_refresh or not self.is_running:
            return
        if len(self.screen_stack) == 1:
            if self._actions_paused and not self._action_waiting and self._scan_done.is_set():
                self._actions_paused = False
                self.refresh_schedule.next_poll = self.refresh_schedule.clock() + 5
            self.publish_deferred()
        if self.scanning or self._actions_paused:
            return
        if self._pending_refresh:
            providers, self._pending_refresh = self._pending_refresh, set()
            self.request_refresh(providers)
        elif self.auto_enabled and self.refresh_schedule.clock() >= self.refresh_schedule.next_poll:
            self.request_refresh(automatic=True)

    def publish_deferred(self, *, force=False):
        if not self._deferred_results or (not force and len(self.screen_stack) > 1):
            return
        from ..discovery import publish_scan

        pending, self._deferred_results = self._deferred_results, []
        if self._deferred_roots:
            self.catalog.invalidate_aliases(
                self._deferred_roots, self._deferred_roots[0]._scan_cycle
            )
            self._deferred_roots = []
        for root, result in pending:
            self.source_status.append(publish_scan(self.catalog, root, result))
        self.reload_rows()

    async def reader_call(self, function, *args):
        reader = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(reader)
        except asyncio.CancelledError:
            self._stopping_refresh = True
            self._cancel_scan.set()
            await reader
            raise

    async def refresh_catalog(self, providers=None, *, automatic=False):
        from ..discovery import READ_ERRORS, iter_scan, prepare_scan, publish_scan

        if self._stopping_refresh:
            self.scanning = False
            self._scan_done.set()
            return
        if self._scan_task is not None:
            self._pending_refresh.update(
                providers
                or self.filters.get("providers")
                or [r.provider for r in self.config.roots if r.enabled]
            )
            return
        self._scan_task = asyncio.current_task()
        self.scanning = True
        self._scan_done.clear()
        self._cancel_scan = threading.Event()
        stream = None
        outcomes = {}
        self.last_refresh = "checking" if automatic else "scanning"
        self.update_status()
        try:
            # Do not consume newer stamps while older results await a dialog.
            if self._deferred_results and len(self.screen_stack) > 1:
                if not automatic:
                    self._pending_refresh.update(
                        providers
                        or self.filters.get("providers")
                        or [r.provider for r in self.config.roots if r.enabled]
                    )
                return
            if self._deferred_results:
                self.publish_deferred()
            if automatic:
                roots = [
                    r
                    for r in self.config.roots
                    if r.enabled and (not providers or r.provider in providers)
                ]
                observations = await self.reader_call(observe_roots, roots)
                providers = self.refresh_schedule.changed(roots, observations)
                if not providers:
                    self.last_refresh = "unchanged"
                    if len(self.screen_stack) == 1:
                        spec = QuerySpec(query=self.query, scope=self.scope, **self.filters)
                        if self.catalog.query_page(spec, 0, 0).revision != self._revision:
                            self.reload_rows()
                    return
            roots, arguments = prepare_scan(
                self.config,
                self.catalog,
                providers if providers is not None else self.filters.get("providers"),
                invalidate=False,
            )
            stream = iter_scan(arguments, self._cancel_scan)
            self.source_status = []
            while True:
                scanned = await self.reader_call(next, stream, None)
                if scanned is None:
                    break
                index, result = scanned
                root = roots[index]
                if self._stopping_refresh or result.reason == "cancelled":
                    continue
                if result.stage != "metadata":
                    complete = result.complete and all(
                        "partial" not in (s.history_state, s.search_state, s.usage_state)
                        for s in result.sessions
                    )
                    outcomes[root.provider] = outcomes.get(root.provider, True) and complete
                if automatic and (len(self.screen_stack) > 1 or self._deferred_results):
                    if not self.source_status:
                        self._deferred_roots = roots
                    self._deferred_results.append((root, result))
                else:
                    if not self.source_status:
                        self.catalog.invalidate_aliases(roots, roots[0]._scan_cycle)
                    self.source_status.append(publish_scan(self.catalog, root, result))
                    self.reload_rows()
                await asyncio.sleep(0)
            self.last_refresh = "complete" if all(outcomes.values()) else "incomplete; retry in 30s"
            if self._deferred_results:
                self.last_refresh += "; waiting for dialog"
        except asyncio.CancelledError:
            self._stopping_refresh = True
            raise
        except READ_ERRORS:
            self.last_refresh = "incomplete; retry in 30s"
            outcomes = {
                r.provider: False
                for r in self.config.roots
                if r.enabled and (not providers or r.provider in providers)
            }
        finally:
            self._cancel_scan.set()
            try:
                if stream is not None:
                    await self.reader_call(stream.close)
            finally:
                self.refresh_schedule.finished(outcomes)
                self.scanning = False
                self._scan_task = None
                self._scan_done.set()
                if not self._stopping_refresh:
                    self.update_status()

    def after_readers(self, callback):
        """Freeze the action's identities before yielding to any in-flight reader."""
        self._actions_paused = True
        self._action_waiting = True

        def ready():
            try:
                self.publish_deferred(force=True)
                callback()
            finally:
                self._action_waiting = False

        if not self.scanning:
            ready()
        else:

            async def wait_for_readers():
                await self._scan_done.wait()
                if not self._stopping_refresh:
                    ready()

            self.run_worker(wait_for_readers, group="action")

    def validate_observations(self, sessions):
        from ..models import Failure

        for selected in sessions:
            current = self.catalog.get(selected.session_uid)
            if current.presence != "present" or any(
                getattr(current, key) != getattr(selected, key)
                for key in ("root_id", "locator", "fingerprint", "cwd")
            ):
                raise Failure("source_changed", 5)

    async def stop_readers(self):
        self._stopping_refresh = True
        self._cancel_scan.set()
        if self._scan_task is None:
            self.scanning = False
            self._scan_done.set()
        elif self.scanning:
            await self._scan_done.wait()
        self._pending_refresh.clear()
        self._deferred_results.clear()

    async def action_quit(self):
        await self.stop_readers()
        self.exit()

    async def on_unmount(self):
        await self.stop_readers()

    def action_details(self):
        from .screens import DetailsScreen

        uid = self.selected_uid()
        if uid:
            self.push_screen(DetailsScreen(self.catalog, uid))

    def action_filters(self):
        from .screens import FiltersScreen

        self.push_screen(FiltersScreen(self.filters, self.scope), self.apply_filters)

    def apply_filters(self, value):
        if value is None:
            return
        from ..models import Failure
        from ..search import QuerySpec

        value = dict(value)
        scope = value.pop("scope", self.scope)
        try:
            QuerySpec(scope=scope, **value).filter([])
        except Failure as failure:
            self.push_screen(TextScreen(explain(failure.code)))
            return
        self.scope, self.filters = scope, value
        self.reload_rows()

    def on_data_table_row_selected(self):
        self.action_details()

    def action_search(self):
        self.query_one("#query", Input).focus()

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id != "query":
            return
        self.query = event.value
        self.reload_rows()
        self.query_one("#sessions", DataTable).focus()

    def action_reset(self):
        self.query = ""
        self.filters = {}
        self.scope = "visible"
        self.query_one("#query", Input).value = ""
        self.reload_rows()

    def action_resume(self):
        uid = self.selected_uid()
        if uid:
            selected = self.catalog.get(uid)
            self.after_readers(lambda: self.open_resume(uid, selected))

    def open_resume(self, uid, selected):
        from ..models import Failure
        from .screens import ResumeScreen

        try:
            self.validate_observations([selected])
            self.push_screen(
                ResumeScreen(selected.cwd, session=selected),
                lambda value: self._resume_choice(value, uid=uid, selected=selected),
            )
        except Failure as failure:
            self.push_screen(TextScreen(explain(failure.code)))

    def _resume_choice(self, value, *, uid, selected):
        if value:
            self.resume_selected(*value, uid=uid, selected=selected)

    def resume_selected(self, target, cwd, *, uid=None, selected=None):
        if self.scanning:
            self.notify("Wait for refresh to finish before resume", severity="warning")
            return
        from ..launch import build_request, launch_current
        from ..models import Failure
        from ..warp import deliver
        from .screens import ResumeScreen

        uid = uid or self.selected_uid()
        if not uid:
            return
        try:
            session = self.catalog.get(uid)
            if selected is not None and (
                session.presence != "present"
                or any(
                    getattr(session, key) != getattr(selected, key)
                    for key in ("root_id", "locator", "fingerprint", "cwd")
                )
            ):
                raise Failure("source_changed", 5)
            root = next(
                (r for r in self.config.roots if r.enabled and r.root_id == session.root_id), None
            )
            if root is None:
                raise Failure("resume_binding_unverified", 4)
            request = build_request(root, session, self.config.data_dir, cwd=cwd, target=target)
            if target == "warp":
                result = deliver(self.catalog, request)
            else:
                with self.suspend():
                    result = launch_current(request)
                refresh(self.config, self.catalog, providers=[root.provider])
            self.reload_rows()
            self.notify(result.get("message") or result["state"])
        except Failure as failure:
            guide = failure.data.get("manual_resume_guide")
            if guide:
                selected = selected or session
                self.push_screen(
                    ResumeScreen(cwd, guide, session=selected),
                    lambda value: self._resume_choice(value, uid=uid, selected=selected),
                )
            else:
                self.push_screen(TextScreen(explain(failure.code)))

    def selected_ids(self):
        return (
            sorted(self.batch_selection)
            if self.batch_selection
            else [self.selected_uid()]
            if self.selected_uid()
            else []
        )

    def action_toggle_selection(self):
        uid = self.selected_uid()
        if uid:
            if uid in self.batch_selection:
                self.batch_selection.remove(uid)
            else:
                self.batch_selection.add(uid)
            self.reload_rows()

    def action_hide(self):
        ids = self.selected_ids()
        sessions = [self.catalog.get(uid) for uid in ids]
        if sessions:
            self.catalog.hide(ids, not all(s.hidden for s in sessions))
            self.batch_selection.clear()
            self.reload_rows()

    def action_scope(self):
        self.scope = {"visible": "hidden", "hidden": "all", "all": "visible"}[self.scope]
        self.reload_rows()

    def cleanup_preview(self, action, ids):
        ids = list(ids)
        sessions = [self.catalog.get(uid) for uid in ids] if action == "trash" else []
        self.after_readers(lambda: self._cleanup_preview(action, ids, sessions))

    def _cleanup_preview(self, action, ids, sessions):
        import sqlite3

        if self.scanning:
            self.notify("Wait for refresh to finish before cleanup", severity="warning")
            return
        from ..cleanup import CleanupService
        from ..models import Failure
        from .screens import CleanupScreen

        try:
            self.validate_observations(sessions)
            service = CleanupService(self.config, self.catalog)
            plan = (
                service.recovery_preview(ids[0])
                if action == "cleanup-retry"
                else service.preview(action, ids)
            )
        except (Failure, OSError, sqlite3.Error) as failure:
            self.push_screen(
                TextScreen(explain(failure.code if isinstance(failure, Failure) else "io_error"))
            )
            return

        def confirmed(closed):
            import json

            try:
                result = (
                    service.retry(ids[0], assert_closed=closed)
                    if action == "cleanup-retry"
                    else service.commit(
                        action, ids, plan["confirmation_token"], assert_closed=closed
                    )
                )
                self.batch_selection.clear()
                self.reload_rows()
                self.push_screen(
                    TextScreen(json.dumps(human_data(result), ensure_ascii=False, indent=2))
                )
            except (Failure, OSError, sqlite3.Error) as failure:
                self.push_screen(
                    TextScreen(
                        explain(failure.code if isinstance(failure, Failure) else "io_error")
                    )
                )

        self.push_screen(CleanupScreen(plan, confirmed))

    def action_delete(self):
        if self.selected_ids():
            self.cleanup_preview("trash", self.selected_ids())

    def action_trash(self):
        import sqlite3

        from ..cleanup import CleanupService
        from ..models import Failure
        from .screens import TrashScreen

        try:
            service = CleanupService(self.config, self.catalog)
            listing = service.trash_list()
        except (Failure, OSError, sqlite3.Error) as failure:
            self.push_screen(
                TextScreen(
                    explain(failure.code if isinstance(failure, Failure) else "catalog_read_failed")
                )
            )
            return
        self.push_screen(TrashScreen(listing, self.cleanup_preview))

    def action_statistics(self):
        from ..search import QuerySpec
        from .screens import StatisticsScreen

        spec = QuerySpec(scope=self.stats_scope, query=self.query, **self.filters)
        self.push_screen(
            StatisticsScreen(
                self.catalog,
                self.catalog.sessions(),
                spec=spec,
                session_ids=sorted(self.batch_selection) or None,
                scope_changed=lambda scope: setattr(self, "stats_scope", scope),
            )
        )

    def action_archive(self):
        ids = self.selected_ids()
        if len(ids) != 1:
            self.notify(
                "Select one Codex session; its descendants are included in preview",
                severity="warning",
            )
            return
        self.native_archive_preview("archive", ids[0])

    def action_archives(self):
        import sqlite3

        from ..models import Failure
        from ..native_archive import ArchiveService
        from .screens import ArchivesScreen

        try:
            service = ArchiveService(self.config, self.catalog)
            listing = service.list()
        except (Failure, OSError, sqlite3.Error) as failure:
            self.push_screen(
                TextScreen(
                    explain(failure.code if isinstance(failure, Failure) else "catalog_read_failed")
                )
            )
            return
        self.push_screen(ArchivesScreen(listing, self.native_archive_preview))

    def native_archive_preview(self, action, selector):
        sessions = [self.catalog.get(selector)] if action == "archive" else []
        self.after_readers(lambda: self._native_archive_preview(action, selector, sessions))

    def _native_archive_preview(self, action, selector, sessions):
        if self.scanning:
            self.notify("Wait for refresh to finish before native archive", severity="warning")
            return
        from ..models import Failure
        from ..native_archive import ArchiveService
        from .screens import CleanupScreen

        try:
            self.validate_observations(sessions)
            service = ArchiveService(self.config, self.catalog)
            if action == "archive-retry":
                operation = next(
                    (op for op in service.operations() if op["operation_id"] == selector), None
                )
                if operation is None:
                    raise Failure("operation_not_found", 2)
                plan = {
                    **operation,
                    "action": "archive-retry",
                    "requires_assert_closed": True,
                    "effect": "Retry the same confirmed native IDs; no new sessions are added.",
                }
            else:
                plan = service.preview(action, selector)
        except Failure as failure:
            self.push_screen(TextScreen(explain(failure.code)))
            return

        def confirmed(closed):
            import json

            if self.scanning:
                self.notify("Wait for refresh to finish before native archive", severity="warning")
                return
            try:
                result = (
                    service.retry(selector, assert_closed=closed)
                    if action == "archive-retry"
                    else service.commit(
                        action, selector, plan["confirmation_token"], assert_closed=closed
                    )
                )
                self.batch_selection.clear()
                self.reload_rows()
                if result["state"] == "complete":
                    self.request_refresh(providers=["codex"])
                self.push_screen(
                    TextScreen(json.dumps(human_data(result), ensure_ascii=False, indent=2))
                )
            except Failure as failure:
                self.push_screen(TextScreen(explain(failure.code)))

        self.push_screen(CleanupScreen(plan, confirmed))
