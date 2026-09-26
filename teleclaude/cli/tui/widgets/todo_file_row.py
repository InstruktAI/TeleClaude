"""Artifact row within an expanded todo."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR
from teleclaude.cli.tui.utils.formatters import format_time

_CONNECTOR = Style(color=CONNECTOR_COLOR)
_TIMESTAMP = Style(dim=True)
_TIMESTAMP_SEPARATOR = " "
_TIMESTAMP_OPEN = "["
_TIMESTAMP_CLOSE = "]"


class TodoFileRow(TelecMixin, Widget):
    """Single artifact entry in an expanded todo's tree."""

    class Pressed(Message):
        """Posted when a file row is clicked."""

        def __init__(self, file_row: TodoFileRow) -> None:
            super().__init__()
            self.file_row = file_row

    DEFAULT_CSS = """
    TodoFileRow {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        *,
        artifact_name: str,
        filename: str,
        slug: str,
        project_path: str,
        todo_id: str | None = None,
        updated_at: str | None = None,
        is_last: bool = False,
        tree_lines: list[bool] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.artifact_name = artifact_name
        self.filename = filename
        self.slug = slug
        self.project_path = project_path
        self.todo_id = todo_id
        self.updated_at = updated_at
        self.is_last = is_last
        self._tree_lines = tree_lines or []

    def render(self) -> Text:
        """Render the file name with tree connectors matching its parent todo."""
        line = Text()
        is_selected = self.has_class("selected")
        # Tree prefix: same ancestor lines as parent todo, then file connector
        line.append("  ", style=_CONNECTOR)
        for continues in self._tree_lines:
            line.append("\u2502 " if continues else "  ", style=_CONNECTOR)
        connector = "\u2514" if self.is_last else "\u251c"
        line.append(f"{connector}\u2500", style=_CONNECTOR)
        name_style = Style(reverse=True) if is_selected else Style()
        if self.updated_at:
            line.append(_TIMESTAMP_OPEN, style=_TIMESTAMP)
            line.append(format_time(self.updated_at, with_date=True), style=_TIMESTAMP)
            line.append(_TIMESTAMP_CLOSE, style=_TIMESTAMP)
            line.append(_TIMESTAMP_SEPARATOR, style=_TIMESTAMP)
        line.append(self.filename, style=name_style)
        return line

    def on_click(self, event: Click) -> None:
        """Emit a pressed message when the row is clicked."""
        event.stop()
        self.post_message(self.Pressed(self))
