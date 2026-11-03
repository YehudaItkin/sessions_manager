from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Input, Static

from ..discovery import refresh
from ..messages import explain, human_data
from ..models import safe_text
from .screens import TextScreen


class SessionsApp(App):
    TITLE = "Sessions Manager"
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
        self.batch_selection = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Cached catalog; F5 refreshes configured roots", id="status", markup=False)
        yield Input(placeholder="Literal search; Enter applies, Escape resets", id="query")
        yield DataTable(id="sessions", cursor_type="row")
        yield Footer()

    def on_mount(self):
        table = self.query_one("#sessions", DataTable)
        for label, width in [
            ("Manager ID", 12),
            ("Native ID", 22),
            ("Source", 7),
            ("Title / preview", 28),
            ("Project", 26),
            ("Created", 17),
            ("Last activity", 17),
            ("Activity", 9),
            ("Actions", 24),
        ]:
            table.add_column(label, width=width)
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
        for s in QuerySpec(query=self.query, scope=self.scope, **self.filters).filter(
            self.catalog.sessions(), self.catalog
        ):
            table.add_row(
                handles[s.session_uid],
                Text(safe_text(s.native_id), overflow="ellipsis", no_wrap=True),
                s.provider,
                ("* " if s.session_uid in self.batch_selection else "")
                + safe_text(s.title or s.preview or ""),
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

    def action_refresh(self):
        if not self.scanning:
            self.run_worker(self.refresh_catalog(), group="scan", exclusive=True)

    async def refresh_catalog(self):
        import asyncio

        from ..discovery import collect_scan, prepare_scan, publish_scan

        self.scanning = True
        self.query_one("#status", Static).update("Scanning configured source roots…")
        try:
            roots, arguments = prepare_scan(
                self.config, self.catalog, self.filters.get("providers")
            )
            results = await asyncio.to_thread(collect_scan, arguments)
            self.source_status = []
            for root, result in zip(roots, results, strict=True):
                self.query_one("#status", Static).update(f"Indexing {root.provider}…")
                await asyncio.sleep(0)
                self.source_status.append(publish_scan(self.catalog, root, result))
            self.reload_rows()
        finally:
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

        rows = QuerySpec(scope="all", query=self.query, **self.filters).filter(
            self.catalog.sessions(), self.catalog
        )
        if self.batch_selection:
            rows = [s for s in rows if s.session_uid in self.batch_selection]
        self.push_screen(StatisticsScreen(self.catalog, rows))
