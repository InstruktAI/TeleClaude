"""Shared closing separator for project groups in tree views."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR


class GroupSeparator(TelecMixin, Static):
    """Separator line in tree views.

    Without a label: closing line ─┴─── merging the tree connector.
    With a label: sub-header  │  ── label ── within the tree.
    """

    DEFAULT_CSS = """
    GroupSeparator {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, connector_col: int = 2, label: str | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._connector_col = connector_col
        self._label = label

    def render(self) -> Text:
        width = max(self.size.width, 40)
        col = self._connector_col
        line = Text()
        sep_style = Style(color=CONNECTOR_COLOR)

        if self._label:
            line.append(" " * col, style=sep_style)
            line.append("\u2502", style=sep_style)
            line.append("  \u2500\u2500 ", style=sep_style)
            line.append(self._label, style=Style(dim=True))
            remaining = max(width - col - 5 - len(self._label), 1)
            line.append(" " + "\u2500" * remaining, style=sep_style)
        else:
            line.append("\u2500" * col, style=sep_style)
            line.append("\u2534", style=sep_style)
            line.append("\u2500" * max(width - col - 1, 0), style=sep_style)
        return line
