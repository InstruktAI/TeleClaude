"""Todo display row for preparation view."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.tui.todos import TodoItem


class TodoRow(Widget):
    """Single todo item row in the preparation tree."""

    DEFAULT_CSS = """
    TodoRow {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    """

    expanded = reactive(False)

    def __init__(self, todo: TodoItem, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.todo = todo

    @property
    def slug(self) -> str:
        return self.todo.slug

    def _status_style(self) -> str:
        status = self.todo.status.value
        if status == "ready":
            return "green"
        if status == "in_progress":
            return "yellow"
        return "dim"

    def _build_phase_tags(self) -> Text:
        """Build compact phase tags (B, R, DOR, DEF, F)."""
        tags = Text()
        if self.todo.build_status:
            status = self.todo.build_status
            style = "green" if status == "complete" else "yellow" if status == "pending" else "red"
            tags.append(f" B:{status[0].upper()}", style=style)
        if self.todo.review_status:
            status = self.todo.review_status
            style = "green" if status in ("complete", "approved") else "yellow"
            tags.append(f" R:{status[0].upper()}", style=style)
        if self.todo.dor_score is not None:
            style = "green" if self.todo.dor_score >= 80 else "yellow" if self.todo.dor_score >= 50 else "red"
            tags.append(f" DOR:{self.todo.dor_score}", style=style)
        if self.todo.deferrals_status:
            tags.append(f" DEF:{self.todo.deferrals_status[0].upper()}", style="dim")
        if self.todo.findings_count:
            tags.append(f" F:{self.todo.findings_count}", style="yellow")
        return tags

    def render(self) -> Text:
        line = Text()

        # Status badge
        status_label = self.todo.status.display_label
        line.append(f"  [{status_label}]", style=self._status_style())
        line.append(" ")

        # Slug/name
        line.append(self.todo.slug, style="bold")

        # Description
        if self.todo.description:
            desc = self.todo.description[:50]
            line.append(f"  {desc}", style="dim")

        # Phase tags
        line.append_text(self._build_phase_tags())

        # File indicators
        if self.todo.has_requirements:
            line.append(" 📋", style="")
        if self.todo.has_impl_plan:
            line.append(" 📐", style="")

        # Expanded file list
        if self.expanded and self.todo.files:
            for f in sorted(self.todo.files):
                line.append(f"\n      {f}", style="dim")

        return line

    def watch_expanded(self, _value: bool) -> None:
        self.refresh()
