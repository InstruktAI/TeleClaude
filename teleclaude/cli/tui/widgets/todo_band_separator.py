"""Tree-connected separator for active todo ordering bands."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR, get_neutral_color


class TodoBandSeparator(TelecMixin, Static):
    """Branch-style separator labeling an active todo band."""

    DEFAULT_CSS = """
    TodoBandSeparator {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, *, band: str, label: str, line_width: int = 40, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.band = band
        self.label = label
        self._line_width = line_width

    def render(self) -> Text:
        line = Text(no_wrap=True)
        sep_style = Style(color=CONNECTOR_COLOR)
        label_style = Style(color=get_neutral_color("highlight"), bold=True)
        line.append("  ", style=sep_style)
        line.append("├", style=sep_style)
        line.append("─ ", style=sep_style)
        line.append(self.label, style=label_style)
        line.append(" ", style=sep_style)
        outer_w = self.outer_size.width
        used = 5 + len(self.label)
        line_width = min(self._line_width, max(0, outer_w - used - 2)) if outer_w > 0 else self._line_width
        line.append("─" * line_width, style=sep_style)
        return line
