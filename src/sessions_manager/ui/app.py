from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from ..discovery import refresh
from ..messages import explain, human_data
from ..models import safe_text
from .screens import TextScreen


class SessionsApp(App):
    TITLE = "Sessions Manager"
    CSS = """
    #view-controls { height: 3; }
    #view-controls Button { margin-right: 1; }
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

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Cached catalog; F5 refreshes configured roots", id="status", markup=False)
        with Horizontal(id="view-controls"):
            yield Button("Filters / sort (f)", id="filter-sort")
            yield Button("Reset all (Esc)", id="reset-view")
        yield Static("", id="selection-summary", markup=False)
        yield Input(placeholder="Literal search; Enter applies, Escape resets", id="query")
        yield DataTable(id="sessions", cursor_type="row")
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
        if not self.catalog.root_states():
            self.action_refresh()

    def selected_uid(self):
        table = self.query_one("#sessions", DataTable)
        if table.row_count:
            return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        return None

    def reload_rows(self):
        table = self.query_one("#sessions", DataTable)
        previous = self.selected_uid()
        table.clear()
        from rich.text import Text

        from ..models import display_time, short_handles
        from ..search import QuerySpec

        all_sessions = self.catalog.sessions(include_missing=True)
        handles = short_handles(all_sessions)
        spec = QuerySpec(query=self.query, scope=self.scope, **self.filters)
        rows = spec.filter(
            [s for s in all_sessions if s.presence in ("present", "source_unavailable")],
            self.catalog,
        )
        self.batch_selection.intersection_update(s.session_uid for s in rows)
        self.query_one("#selection-summary", Static).update(safe_text(spec.describe()))
        for s in rows:
            match = self.catalog.match_context(s.session_uid, self.query) if self.query else None
            preview = f"{match['field']}: {match['text']}" if match else s.title or s.preview
            table.add_row(
                handles[s.session_uid],
                Text(safe_text(s.native_id), overflow="ellipsis", no_wrap=True),
                s.provider,
                Text(("* " if s.session_uid in self.batch_selection else "") + safe_text(preview)),
                safe_text(s.cwd),
                display_time(s.created_at),
                display_time(s.last_activity_at),
                s.activity,
                " ".join(
                    key
                    for key in ("history", "resume", "cleanup", "usage")
                    if s.capabilities[key].state == "supported"
                ),
                key=s.session_uid,
            )
        if previous in table.rows:
            table.move_cursor(row=table.get_row_index(previous))
        import json

        from ..models import display_time
        from ..search import local_zone

        states = self.catalog.root_states()
        health = ", ".join(json.loads(r["payload"])["provider"] + ":" + r["state"] for r in states)
        known = [r["as_of"] for r in states if r["as_of"] is not None]
        hidden = sum(session.hidden for session in all_sessions)
        trash = self.catalog.connection.execute(
            "SELECT count(*) FROM sessions WHERE presence='trashed'"
        ).fetchone()[0]
        self.query_one("#status", Static).update(
            f"{table.row_count} {self.scope}; {len(self.batch_selection)} selected; hidden {hidden}; trash {trash} | cached {display_time(min(known) if known else None)} ({local_zone()}) | {health or 'No source roots; use sources add'}"
        )

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "filter-sort":
            self.action_filters()
        elif event.button.id == "reset-view":
            self.action_reset()

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
        if not self.scanning:
            self.run_worker(self.refresh_catalog(), group="scan", exclusive=True)

    async def refresh_catalog(self):
        import asyncio
        import threading

        from ..discovery import iter_scan, prepare_scan, publish_scan

        self.scanning = True
        cancel = threading.Event()
        self.query_one("#status", Static).update("Scanning configured source roots…")
        try:
            roots, arguments = prepare_scan(
                self.config, self.catalog, self.filters.get("providers")
            )
            stream = iter_scan(arguments, cancel)
            self.source_status = []
            while (scanned := await asyncio.to_thread(next, stream, None)) is not None:
                index, result = scanned
                root = roots[index]
                self.query_one("#status", Static).update(f"Indexing {root.provider}…")
                self.source_status.append(publish_scan(self.catalog, root, result))
                self.reload_rows()
                await asyncio.sleep(0)
        finally:
            cancel.set()
            self.scanning = False

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
        from .screens import ResumeScreen

        uid = self.selected_uid()
        if uid:
            self.push_screen(ResumeScreen(self.catalog.get(uid).cwd), self._resume_choice)

    def _resume_choice(self, value):
        if value:
            self.resume_selected(*value)

    def resume_selected(self, target, cwd):
        if self.scanning:
            self.notify("Wait for refresh to finish before resume", severity="warning")
            return
        from ..launch import build_request, launch_current
        from ..models import Failure
        from ..warp import deliver
        from .screens import ResumeScreen

        uid = self.selected_uid()
        if not uid:
            return
        session = self.catalog.get(uid)
        root = next((r for r in self.config.roots if r.root_id == session.root_id), None)
        try:
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
                self.push_screen(ResumeScreen(cwd, guide), self._resume_choice)
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
        if self.scanning:
            self.notify("Wait for refresh to finish before cleanup", severity="warning")
            return
        from ..cleanup import CleanupService
        from ..models import Failure
        from .screens import CleanupScreen

        service = CleanupService(self.config, self.catalog)
        try:
            plan = service.preview(action, ids)
        except Failure as failure:
            self.push_screen(TextScreen(explain(failure.code)))
            return

        def confirmed(closed):
            import json

            try:
                result = service.commit(
                    action, ids, plan["confirmation_token"], assert_closed=closed
                )
                self.batch_selection.clear()
                self.reload_rows()
                self.push_screen(
                    TextScreen(json.dumps(human_data(result), ensure_ascii=False, indent=2))
                )
            except Failure as failure:
                self.push_screen(TextScreen(explain(failure.code)))

        self.push_screen(CleanupScreen(plan, confirmed))

    def action_delete(self):
        if self.selected_ids():
            self.cleanup_preview("trash", self.selected_ids())

    def action_trash(self):
        from ..cleanup import CleanupService
        from .screens import TrashScreen

        service = CleanupService(self.config, self.catalog)
        self.push_screen(TrashScreen(service.trash_list(), self.cleanup_preview))

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
