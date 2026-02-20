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

    def __init__(self, slug: str, filename: str, is_last: bool = False, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.slug = slug
        self.filename = filename
        self.is_last = is_last

    def render(self) -> Text:
        line = Text()
        is_selected = self.has_class("selected")
        connector = "\u2514" if self.is_last else "\u251c"
        line.append(f"  \u2502 {connector}\u2500", style=_CONNECTOR)
        name_style = Style(reverse=True) if is_selected else Style()
        line.append(self.filename, style=name_style)
        return line

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(self.Pressed(self))
