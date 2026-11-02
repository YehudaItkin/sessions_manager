from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

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
        import json

        from textual.widgets import Input

        with VerticalScroll():
            yield Static("Resume exact native session", markup=False)
            if self.guide:
                yield Static(
                    safe_text(json.dumps(self.guide, ensure_ascii=False, indent=2)), markup=False
                )
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
                "IRREVERSIBLE PURGE" if self.plan["action"] == "purge" else "Exact cleanup preview",
                markup=False,
            )
            yield Static(
                safe_text(json.dumps(self.plan, ensure_ascii=False, indent=2)), markup=False
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
    BINDINGS = [("escape", "cancel", "Close")]

    def __init__(self, items, on_action):
        super().__init__()
        self.items = items
        self.on_action = on_action

    def compose(self):
        from textual.widgets import DataTable

        yield Static("Manager trash: exact recoverable entries and recovery states", markup=False)
        yield DataTable(id="trash-table", cursor_type="row")
        yield Button("Close", id="cancel")
        yield Button("Restore selected", id="restore")
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
        from textual.widgets import DataTable

        if event.button.id == "cancel":
            self.dismiss(None)
            return
        table = self.query_one(DataTable)
        if not table.row_count:
            return
        key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        self.dismiss(None)
        self.on_action(event.button.id, [key])


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
        from ..models import display_time

        session = self.catalog.get(self.uid)
        rows = self.catalog.events(self.uid, self.history_offset, 101)
        header = f"Manager ID: {session.display_id}\nNative ID: {session.native_id or 'unknown'}\nSource: {session.provider}\nProject: {session.cwd or 'unknown'}\nCreated: {display_time(session.created_at)}\nLast activity: {display_time(session.last_activity_at)}\nHistory: {session.history_state}\n"
        header += "\n".join(
            f"{key}: {value.state}" + (f" ({value.reason})" if value.reason else "")
            for key, value in session.capabilities.items()
        )
        from ..statistics import summarize

        header += f"\nHistory location: {session.locator}\nModel: {session.model or 'unknown'}\n"
        for name, metric in summarize(self.catalog, [session])["metrics"].items():
            header += f"{name}: {metric['value'] if metric['value'] is not None else 'unknown'} ({metric.get('reason') or 'complete'})\n"
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

    def __init__(self, current, scope):
        super().__init__()
        self.current, self.scope = current, scope

    def compose(self):
        from textual.widgets import Input, Select

        with VerticalScroll():
            yield Static(
                "Filters (all use AND; refresh still reads every session in chosen source roots)",
                markup=False,
            )
            yield Select(
                [
                    ("All sources", "all"),
                    ("Codex", "codex"),
                    ("Claude", "claude"),
                    ("Grok", "grok"),
                    ("Cursor", "cursor"),
                ],
                value=(self.current.get("providers") or ["all"])[0],
                allow_blank=False,
                id="source-filter",
            )
            yield Input(
                value=self.current.get("project") or "",
                placeholder="Project contains",
                id="project-filter",
            )
            yield Input(
                value=self.current.get("since") or "",
                placeholder="Since: YYYY-MM-DD or ISO timestamp",
                id="since-filter",
            )
            yield Input(
                value=self.current.get("until") or "",
                placeholder="Until: YYYY-MM-DD or ISO timestamp",
                id="until-filter",
            )
            yield Select(
                [("Visible", "visible"), ("Hidden", "hidden"), ("All", "all")],
                value=self.scope,
                allow_blank=False,
                id="scope-filter",
            )
            yield Select(
                [("Newest first", "recent"), ("Oldest first", "oldest")],
                value=self.current.get("sort", "recent"),
                allow_blank=False,
                id="sort-filter",
            )
            yield Button("Apply", id="apply")
            yield Button("Cancel", id="cancel")

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event):
        from textual.widgets import Input, Select

        if event.button.id == "cancel":
            self.dismiss(None)
            return
        source = self.query_one("#source-filter", Select).value
        self.dismiss(
            {
                "providers": None if source == "all" else [source],
                "project": self.query_one("#project-filter", Input).value or None,
                "since": self.query_one("#since-filter", Input).value or None,
                "until": self.query_one("#until-filter", Input).value or None,
                "scope": self.query_one("#scope-filter", Select).value,
                "sort": self.query_one("#sort-filter", Select).value,
            }
        )


class StatisticsScreen(ModalScreen):
    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    def __init__(self, catalog, sessions):
        super().__init__()
        self.catalog, self.sessions = catalog, sessions

    def compose(self):
        from textual.widgets import Select

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

        self.query_one("#stats-content", Static).update(
            safe_text(
                json.dumps(
                    summarize(self.catalog, self.sessions, group_by=group),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        )

    def on_select_changed(self, event):
        if event.select.id == "stats-group" and event.value in ("source", "project", "day"):
            self.render_statistics(event.value)

    def on_button_pressed(self, event):
        self.action_close()

    def action_close(self):
        self.dismiss(None)
