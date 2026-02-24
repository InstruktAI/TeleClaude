"""Jobs view displaying scheduled and one-shot jobs."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.models import JobInfo
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.widgets.job_row import JobRow


class SectionHeader(TelecMixin, Widget):
    """Section header divider in the jobs list."""

    DEFAULT_CSS = """
    SectionHeader {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, title: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._title = title

    def render(self) -> Text:
        return Text(f"── {self._title} ──", style="bold dim")


class JobsView(Widget, can_focus=True):
    """Jobs tab view listing scheduled and one-shot jobs.

    Handles: arrow nav, Enter (run job).
    """

    DEFAULT_CSS = """
    JobsView {
        width: 100%;
        height: 100%;
    }
    JobsView VerticalScroll {
        width: 100%;
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up", key_display="↑", group=Binding.Group("Nav", compact=True)),
        Binding("down", "cursor_down", "Down", key_display="↓", group=Binding.Group("Nav", compact=True)),
        Binding("enter", "run_job", "[b]Run[/b]", key_display="[b]↵[/b]"),
    ]

    cursor_index = reactive(0)

    def watch_cursor_index(self, value: int) -> None:
        """Update cursor highlight and refresh footer bindings on move."""
        self._update_cursor_highlight()
        if self.is_attached:
            self.app.refresh_bindings()

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._jobs: list[JobInfo] = []
        self._nav_items: list[Widget] = []

    def compose(self) -> ComposeResult:
        scroll = VerticalScroll(id="jobs-scroll")
        scroll.can_focus = False
        yield scroll

    def update_data(self, jobs: list[JobInfo]) -> None:
        """Update view with fresh job data."""
        self._jobs = jobs
        self._rebuild()

    def _rebuild(self) -> None:
        container = self.query_one("#jobs-scroll", VerticalScroll)
        container.remove_children()
        self._nav_items.clear()

        # Group by type
        scheduled = [j for j in self._jobs if j.schedule]
        oneshot = [j for j in self._jobs if not j.schedule]

        if scheduled:
            header = SectionHeader("Scheduled")
            container.mount(header)
            for job in scheduled:
                row = JobRow(job=job)
                container.mount(row)
                self._nav_items.append(row)

        if oneshot:
            header = SectionHeader("One-shot")
            container.mount(header)
            for job in oneshot:
                row = JobRow(job=job)
                container.mount(row)
                self._nav_items.append(row)

        if self._nav_items and self.cursor_index >= len(self._nav_items):
            self.cursor_index = max(0, len(self._nav_items) - 1)
        self._update_cursor_highlight()

    def _update_cursor_highlight(self) -> None:
        for i, widget in enumerate(self._nav_items):
            was_selected = widget.has_class("selected")
            is_selected = i == self.cursor_index
            widget.set_class(is_selected, "selected")
            if was_selected != is_selected:
                widget.refresh()

    def _current_job_row(self) -> JobRow | None:
        if not self._nav_items or self.cursor_index >= len(self._nav_items):
            return None
        item = self._nav_items[self.cursor_index]
        return item if isinstance(item, JobRow) else None

    def action_cursor_up(self) -> None:
        if self._nav_items and self.cursor_index > 0:
            self.cursor_index -= 1
            self._update_cursor_highlight()
            if 0 <= self.cursor_index < len(self._nav_items):
                self._nav_items[self.cursor_index].scroll_visible()

    def action_cursor_down(self) -> None:
        if self._nav_items and self.cursor_index < len(self._nav_items) - 1:
            self.cursor_index += 1
            self._update_cursor_highlight()
            if 0 <= self.cursor_index < len(self._nav_items):
                self._nav_items[self.cursor_index].scroll_visible()

    def action_run_job(self) -> None:
        """Enter: run selected job."""
        row = self._current_job_row()
        if row:
            from teleclaude.cli.tui.messages import SettingsChanged

            self.post_message(SettingsChanged(key=f"run_job:{row.job.name}", value=True))
