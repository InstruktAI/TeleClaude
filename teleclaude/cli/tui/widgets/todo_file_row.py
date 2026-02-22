"""File row within an expanded todo — navigable, previewable."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR

_CONNECTOR = Style(color=CONNECTOR_COLOR)


class TodoFileRow(TelecMixin, Widget):
    """Single file entry in an expanded todo's file tree."""

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
        filepath: str,
        filename: str,
        slug: str = "",
        is_last: bool = False,
        tree_lines: list[bool] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.filepath = filepath
        self.filename = filename
        self.slug = slug  # Empty for standalone files (roadmap.yaml)
        self.is_last = is_last
        self._tree_lines = tree_lines or []

    def render(self) -> Text:
        line = Text()
        is_selected = self.has_class("selected")
        # Tree prefix: same ancestor lines as parent todo, then file connector
        line.append("  ", style=_CONNECTOR)
        for continues in self._tree_lines:
            line.append("\u2502 " if continues else "  ", style=_CONNECTOR)
        connector = "\u2514" if self.is_last else "\u251c"
        line.append(f"{connector}\u2500", style=_CONNECTOR)
        name_style = Style(reverse=True) if is_selected else Style()
        line.append(self.filename, style=name_style)
        return line

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(self.Pressed(self))
