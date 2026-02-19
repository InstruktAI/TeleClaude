"""ASCII banner widget with optional animation color overlay."""

from __future__ import annotations

from rich.text import Text
from textual.widget import Widget

from teleclaude.cli.tui.theme import BANNER_COLOR

BANNER_LINES = [
    "████████╗███████╗██╗     ███████╗ ██████╗██╗      █████╗ ██╗   ██╗██████╗ ███████╗",
    "╚══██╔══╝██╔════╝██║     ██╔════╝██╔════╝██║     ██╔══██╗██║   ██║██╔══██╗██╔════╝",
    "   ██║   █████╗  ██║     █████╗  ██║     ██║     ███████║██║   ██║██║  ██║█████╗  ",
    "   ██║   ██╔══╝  ██║     ██╔══╝  ██║     ██║     ██╔══██║██║   ██║██║  ██║██╔══╝  ",
    "   ██║   ███████╗███████╗███████╗╚██████╗███████╗██║  ██║╚██████╔╝██████╔╝███████╗",
    "   ╚═╝   ╚══════╝╚══════╝╚══════╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝",
]

BANNER_HEIGHT = len(BANNER_LINES)


class Banner(Widget):
    """ASCII art banner for the TUI header."""

    DEFAULT_CSS = """
    Banner {
        width: 100%;
        height: 6;
        content-align: center middle;
    }
    """

    def render(self) -> Text:
        result = Text()
        for i, line in enumerate(BANNER_LINES):
            if i > 0:
                result.append("\n")
            result.append(line, style=BANNER_COLOR)
        return result
