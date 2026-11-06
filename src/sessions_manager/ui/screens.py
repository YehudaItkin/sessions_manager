from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ..messages import explain, human_data, resume_guide
from ..models import safe_text


class TextScreen(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close"), ("q", "dismiss", "Close")]

    def __init__(self, text):
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(safe_text(self.text), markup=False)
            yield Button("Close", id="close")

    def on_button_pressed(self):
        self.dismiss()


class ResumeScreen(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, cwd=None, guide=None):
        super().__init__()
        self.cwd = cwd or ""
        self.guide = guide

    def compose(self):
        from textual.widgets import Input

        with VerticalScroll():
            yield Static("Resume exact native session", markup=False)
            if self.guide:
                yield Static(safe_text(resume_guide(self.guide)), markup=False)
            yield Input(value=self.cwd, placeholder="Existing project directory", id="cwd")
            yield Button("Current terminal", id="current")
            yield Button("Warp", id="warp")
            yield Button("Cancel", id="cancel")

    def on_mount(self):
        self.query_one("#cancel", Button).focus()

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event):
        from textual.widgets import Input

        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self.dismiss((event.button.id, self.query_one("#cwd", Input).value))


class CleanupScreen(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, plan, on_confirm):
        super().__init__()
        self.plan = plan
        self.on_confirm = on_confirm

    def compose(self):
        import json

        from textual.widgets import Checkbox

        with VerticalScroll():
            yield Static(
                {
                    "purge": "IRREVERSIBLE PURGE",
                    "trash": "Move selected sessions to trash",
                    "restore": "Restore selected sessions",
                    "archive": "Archive in Codex (history retained)",
                    "unarchive": "Restore original Codex archive flags",
                    "archive-retry": "Retry the same native archive operation",
                }[self.plan["action"]],
                markup=False,
            )
            yield Static(
                safe_text(json.dumps(human_data(self.plan), ensure_ascii=False, indent=2)),
                markup=False,
            )
            if self.plan.get("requires_assert_closed"):
                yield Checkbox(
                    "I confirm these sessions are closed and will remain closed during this operation",
                    id="closed",
                )
            yield Button("Cancel", id="cancel")
            yield Button("Confirm exact operation", id="confirm", variant="error")

    def on_mount(self):
        self.query_one("#cancel", Button).focus()

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            from textual.widgets import Checkbox

            closed = (
                self.query_one("#closed", Checkbox).value
                if self.plan.get("requires_assert_closed")
                else False
            )
            if self.plan.get("requires_assert_closed") and not closed:
                self.notify("Closed-session assertion is required", severity="warning")
                return
            self.dismiss(None)
            self.on_confirm(closed)


class TrashScreen(ModalScreen):
    BINDINGS = [("escape", "cancel", "Close"), ("r", "restore", "Restore")]

    def __init__(self, items, on_action):
        super().__init__()
        self.items = items
        self.on_action = on_action

    def compose(self):
        from textual.widgets import DataTable

        yield Static("Manager trash: exact recoverable entries and recovery states", markup=False)
        yield DataTable(id="trash-table", cursor_type="row")
        yield Button("Close", id="cancel")
        yield Button("Restore selected (r)", id="restore")
        yield Button("Purge selected (irreversible)", id="purge", variant="error")

    def on_mount(self):
        from textual.widgets import DataTable

        table = self.query_one(DataTable)
        table.add_columns("Trash ID", "Session ID", "State", "Actions")
        for item in self.items:
            table.add_row(
                item["trash_id"],
                item["session_id"],
                item["state"],
                ", ".join(item["available_actions"]),
                key=item["trash_id"],
            )
        self.query_one("#cancel", Button).focus()

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self.selected_action(event.button.id)

    def action_restore(self):
        self.selected_action("restore")

    def selected_action(self, action):
        from textual.widgets import DataTable

        table = self.query_one(DataTable)
        if not table.row_count:
            return
        key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        item = next(row for row in self.items if row["trash_id"] == key)
        if action not in item["available_actions"]:
            return
        self.dismiss(None)
        self.on_action(action, [key])


class DetailsScreen(ModalScreen):
    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    def __init__(self, catalog, uid):
        super().__init__()
        self.catalog, self.uid = catalog, uid
        self.history_offset = 0

    def compose(self):
        yield VerticalScroll(Static("", id="history-content", markup=False), id="history-scroll")
        from textual.containers import Horizontal

        with Horizontal():
            yield Button("Previous 100", id="previous-page")
            yield Button("Next 100", id="next-page")
            yield Button("Close", id="close")

    def on_mount(self):
        self.render_page()

    def render_page(self):
        from ..models import display_session_time

        session = self.catalog.get(self.uid)
        rows = self.catalog.events(self.uid, self.history_offset, 101)
        header = f"Manager ID: {session.display_id}\nNative ID: {session.native_id or 'unknown'}\nSource: {session.provider}\nProject: {session.cwd or 'unknown'}\nCreated: {display_session_time(session, 'created_at')}\nLast activity: {display_session_time(session, 'last_activity_at')}\nHistory: {session.history_state}\n"
        if session.extra.get("ambiguous_native_dates"):
            header += "Some native dates are ambiguous (timezone not recorded).\n"
        header += "\n".join(
            f"{key}: {value.state}" + (f" — {explain(value.reason)}" if value.reason else "")
            for key, value in session.capabilities.items()
        )
        from ..statistics import summarize

        header += f"\nHistory location: {session.locator}\nModel: {session.model or 'unknown'}\n"
        for name, metric in summarize(self.catalog, [session])["metrics"].items():
            header += f"{name}: {metric['value'] if metric['value'] is not None else 'unknown'} ({explain(metric['reason']) if metric.get('reason') else 'complete'})\n"
        text = (
            header
            + f"\n\nEvents {self.history_offset + 1}–{self.history_offset + len(rows[:100])}\n"
        )
        for row in rows[:100]:
            text += f"\n{row['role']}: {row.get('text') or '[no text]'}\n"
        self.query_one("#history-content", Static).update(safe_text(text))
        self.query_one("#previous-page", Button).disabled = self.history_offset == 0
        self.query_one("#next-page", Button).disabled = len(rows) <= 100
        self.query_one("#history-scroll").scroll_home(animate=False)

    def action_close(self):
        self.dismiss(None)

    def on_button_pressed(self, event):
        if event.button.id == "close":
            self.dismiss(None)
            return
        self.history_offset = max(
            0, self.history_offset + (-100 if event.button.id == "previous-page" else 100)
        )
        self.render_page()


class FiltersScreen(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    FiltersScreen { align: center middle; }
    FiltersScreen #filter-dialog { width: 90%; max-width: 90; height: 90%; border: round $accent; padding: 1 2; background: $surface; }
    FiltersScreen #filter-fields { height: 1fr; }
    FiltersScreen Label { margin-top: 1; }
    FiltersScreen SelectionList { height: 6; }
    FiltersScreen #filter-buttons { height: 3; margin-top: 1; }
    FiltersScreen #filter-buttons Button { margin-right: 1; min-width: 12; }
    """

    def __init__(self, current, scope):
        super().__init__()
        self.current, self.scope = current, scope

    def compose(self):
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Input, Label, Select, SelectionList

        from ..models import PROVIDERS
        from ..search import SORT_OPTIONS, QuerySpec

        field, order = QuerySpec(**self.current).sorting()
        sources = self.current.get("providers") or PROVIDERS
        with Vertical(id="filter-dialog"):
            yield Static("Filters / sort", markup=False)
            with VerticalScroll(id="filter-fields"):
                yield Label("Sources — select one or more")
                yield SelectionList(
                    *[(p.capitalize(), p, p in sources) for p in PROVIDERS], id="source-filter"
                )
                yield Label("Project contains")
                yield Input(value=self.current.get("project") or "", id="project-filter")
                yield Label("Model contains")
                yield Input(value=self.current.get("model") or "", id="model-filter")
                yield Label("Activity")
                yield Select(
                    [
                        ("Any activity", "all"),
                        ("Active", "active"),
                        ("Inactive", "inactive"),
                        ("Unknown", "unknown"),
                    ],
                    value=self.current.get("activity") or "all",
                    allow_blank=False,
                    id="activity-filter",
                )
                yield Label("Last activity from (inclusive)")
                yield Input(
                    value=self.current.get("since") or "",
                    placeholder="YYYY-MM-DD or ISO timestamp",
                    id="since-filter",
                )
                yield Label("Last activity until (inclusive)")
                yield Input(
                    value=self.current.get("until") or "",
                    placeholder="YYYY-MM-DD or ISO timestamp",
                    id="until-filter",
                )
                yield Label("Visibility")
                yield Select(
                    [("Visible", "visible"), ("Hidden", "hidden"), ("All", "all")],
                    value=self.scope,
                    allow_blank=False,
                    id="scope-filter",
                )
                yield Label("Sort by")
                yield Select(SORT_OPTIONS, value=field, allow_blank=False, id="sort-filter")
                yield Label("Direction")
                yield Select(
                    [("Ascending ↑", "asc"), ("Descending ↓", "desc")],
                    value=order,
                    allow_blank=False,
                    id="order-filter",
                )
            with Horizontal(id="filter-buttons"):
                yield Button("Apply", id="apply", variant="primary")
                yield Button("Reset filters", id="clear-filters")
                yield Button("Cancel", id="cancel")

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event):
        from textual.widgets import Input, Select, SelectionList

        from ..models import PROVIDERS, Failure
        from ..search import QuerySpec

        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id == "clear-filters":
            self.query_one("#source-filter", SelectionList).select_all()
            for field in ("project", "model", "since", "until"):
                self.query_one(f"#{field}-filter", Input).value = ""
            for field, value in (
                ("activity", "all"),
                ("scope", "visible"),
                ("sort", "updated"),
                ("order", "desc"),
            ):
                self.query_one(f"#{field}-filter", Select).value = value
            return
        if event.button.id != "apply":
            return
        sources = self.query_one("#source-filter", SelectionList).selected
        if not sources:
            self.notify(
                "Select at least one source, or reset filters for all sources.", severity="warning"
            )
            return
        value = {
            "providers": None
            if set(sources) == set(PROVIDERS)
            else [p for p in PROVIDERS if p in sources],
            **{
                field: self.query_one(f"#{field}-filter", Input).value or None
                for field in ("project", "model", "since", "until")
            },
            **{
                field: self.query_one(f"#{field}-filter", Select).value
                for field in ("scope", "sort", "order")
            },
            "activity": None
            if self.query_one("#activity-filter", Select).value == "all"
            else self.query_one("#activity-filter", Select).value,
        }
        try:
            QuerySpec(**value).filter([])
        except Failure as failure:
            self.notify(explain(failure.code), severity="error")
            return
        self.dismiss(value)


class StatisticsScreen(ModalScreen):
    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    def __init__(self, catalog, sessions, *, spec=None, session_ids=None, scope_changed=None):
        super().__init__()
        self.catalog, self.sessions = catalog, sessions
        from ..search import QuerySpec

        self.spec = spec or QuerySpec(scope="all")
        self.session_ids, self.scope_changed = session_ids, scope_changed

    def compose(self):
        from textual.widgets import Select

        yield Select(
            [
                ("All sessions (hidden included)", "all"),
                ("Visible sessions", "visible"),
                ("Hidden sessions", "hidden"),
            ],
            value=self.spec.scope,
            allow_blank=False,
            id="stats-scope",
        )
        yield Select(
            [("Source", "source"), ("Project", "project"), ("Last activity day", "day")],
            value="source",
            allow_blank=False,
            id="stats-group",
        )
        yield VerticalScroll(Static("", id="stats-content", markup=False))
        yield Button("Close", id="close")

    def on_mount(self):
        self.render_statistics("source")

    def render_statistics(self, group):
        import json

        from ..statistics import summarize

        rows = self.spec.filter(self.sessions, self.catalog)
        if self.session_ids is not None:
            rows = [s for s in rows if s.session_uid in self.session_ids]
        self.query_one("#stats-content", Static).update(
            safe_text(
                json.dumps(
                    summarize(
                        self.catalog,
                        rows,
                        group_by=group,
                        selection=self.spec.selection(
                            ["s-" + uid for uid in self.session_ids]
                            if self.session_ids is not None
                            else None
                        ),
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        )

    def on_select_changed(self, event):
        if event.select.id == "stats-group" and event.value in ("source", "project", "day"):
            self.render_statistics(event.value)
        elif event.select.id == "stats-scope" and event.value in ("all", "visible", "hidden"):
            from textual.widgets import Select

            self.spec.scope = event.value
            if self.scope_changed:
                self.scope_changed(event.value)
            self.render_statistics(self.query_one("#stats-group", Select).value)

    def on_button_pressed(self, event):
        self.action_close()

    def action_close(self):
        self.dismiss(None)


class ArchivesScreen(ModalScreen):
    """Separate native archives; permanent deletion and manager trash are absent."""

    CSS = "#archive-table { height: 1fr; min-height: 3; }"
    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("u", "unarchive", "Unarchive"),
        ("r", "retry", "Retry operation"),
    ]

    def __init__(self, data, on_action):
        super().__init__()
        self.data, self.on_action = data, on_action
        self.targets = {}

    def compose(self):
        from textual.widgets import DataTable

        yield Static(
            "Cached Codex archives — history stays on disk. F5 in the main view refreshes; pending operations can be retried.",
            markup=False,
        )
        yield DataTable(id="archive-table", cursor_type="row")
        with Horizontal():
            yield Button("Unarchive (u)", id="unarchive")
            yield Button("Retry operation (r)", id="archive-retry")
            yield Button("Close", id="cancel")

    def on_mount(self):
        from textual.widgets import DataTable

        table = self.query_one(DataTable)
        table.add_columns("Manager ID / Operation", "Native ID", "Title / State")
        for session in self.data["items"]:
            key = "session:" + session["display_id"]
            self.targets[key] = ("unarchive", session["display_id"])
            table.add_row(
                session["display_id"],
                safe_text(session["native_id"]),
                safe_text(session["title"] or session["preview"]),
                key=key,
            )
        for operation in self.data["operations"]:
            if operation["state"] in ("complete", "failed_no_change"):
                continue
            key = "operation:" + operation["operation_id"]
            self.targets[key] = ("archive-retry", operation["operation_id"])
            table.add_row(
                operation["operation_id"], operation["action"], operation["state"], key=key
            )
        table.focus()

    def action_cancel(self):
        self.dismiss(None)

    def action_unarchive(self):
        self.selected_action("unarchive")

    def action_retry(self):
        self.selected_action("archive-retry")

    def selected_action(self, action):
        from textual.widgets import DataTable

        table = self.query_one(DataTable)
        if not table.row_count:
            return
        key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        selected, selector = self.targets[key]
        if selected != action:
            return
        self.dismiss(None)
        self.on_action(action, selector)

    def on_button_pressed(self, event):
        if event.button.id == "cancel":
            self.action_cancel()
        else:
            self.selected_action(event.button.id)
