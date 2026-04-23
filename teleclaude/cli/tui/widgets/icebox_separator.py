"""Tree-connected separator between active todos and icebox items."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR


class IceboxSeparator(TelecMixin, Static):
    """Branch-style separator within the todo tree for icebox section."""

    DEFAULT_CSS = """
    IceboxSeparator {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, line_width: int = 40, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._line_width = line_width

    def render(self) -> Text:
        line = Text(no_wrap=True)
        sep_style = Style(color=CONNECTOR_COLOR)
        # Match TodoRow tree prefix: 2-space margin + ├ + ─ for full row width
        line.append("  ", style=sep_style)
        line.append("\u251c", style=sep_style)
        # Rendered prefix is 3 chars ("  " + "├"); content_area = outer_w - 2 (CSS padding: 0 1)
        # So effective line_width = min(natural, outer_w - 5) to stay within content area.
        outer_w = self.outer_size.width
        line_width = min(self._line_width, max(0, outer_w - 5)) if outer_w > 0 else self._line_width
        line.append("\u2500" * line_width, style=sep_style)
        return line
