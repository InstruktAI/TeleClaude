"""Tree-connected separator between icebox and trashed items."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR


class TrashedSeparator(TelecMixin, Static):
    """Branch-style separator within the todo tree for trashed section."""

    DEFAULT_CSS = """
    TrashedSeparator {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    """

    def render(self) -> Text:
        line = Text(no_wrap=True)
        sep_style = Style(color=CONNECTOR_COLOR)
        # Match TodoRow tree prefix: 2-space margin + ├ + ─ filling the pane width.
        line.append("  ", style=sep_style)
        line.append("├", style=sep_style)
        line.append("─" * max(self.size.width - 3, 0), style=sep_style)
        return line
