"""Shared closing separator for project groups in tree views."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR


class GroupSeparator(TelecMixin, Static):
    """Closing line after the last item in a project group.

    Renders ─┴─── where ┴ is at the connector column, merging the
    tree connector into the separator line.
    """

    DEFAULT_CSS = """
    GroupSeparator {
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
        col = self._connector_col
        line = Text()
        sep_style = Style(color=CONNECTOR_COLOR)
        line.append("\u2500" * col, style=sep_style)
        line.append("\u2534", style=sep_style)
        line.append("\u2500" * max(width - col - 1, 0), style=sep_style)
        return line
