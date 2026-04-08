"""Simple horizontal separator between active todos and icebox items."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR


class IceboxSeparator(TelecMixin, Static):
    """Plain horizontal line separating active todos from icebox items."""

    DEFAULT_CSS = """
    IceboxSeparator {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, connector_col: int = 2, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._connector_col = connector_col

    def render(self) -> Text:
        width = max(self.size.width, 40)
        line = Text()
        sep_style = Style(color=CONNECTOR_COLOR)
        line.append("\u2500" * width, style=sep_style)
        return line
