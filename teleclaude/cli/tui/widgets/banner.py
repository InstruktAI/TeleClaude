"""ASCII banner widget."""

import curses
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from teleclaude.cli.tui.animation_engine import AnimationEngine

BANNER_LINES = [
    "████████╗███████╗██╗     ███████╗ ██████╗██╗      █████╗ ██╗   ██╗██████╗ ███████╗",
    "╚══██╔══╝██╔════╝██║     ██╔════╝██╔════╝██║     ██╔══██╗██║   ██║██╔══██╗██╔════╝",
    "   ██║   █████╗  ██║     █████╗  ██║     ██║     ███████║██║   ██║██║  ██║█████╗  ",
    "   ██║   ██╔══╝  ██║     ██╔══╝  ██║     ██║     ██╔══██║██║   ██║██║  ██║██╔══╝  ",
    "   ██║   ███████╗███████╗███████╗╚██████╗███████╗██║  ██║╚██████╔╝██████╔╝███████╗",
    "   ╚═╝   ╚══════╝╚══════╝╚══════╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝",
]

BANNER_HEIGHT = len(BANNER_LINES)


def render_banner(
    stdscr: object, start_row: int, width: int, animation_engine: Optional["AnimationEngine"] = None
) -> int:
    """Render ASCII banner.

    Args:
        stdscr: Curses screen object
        start_row: Starting row
        width: Screen width
        animation_engine: Optional animation engine for colors

    Returns:
        Number of rows used
    """
    from teleclaude.cli.tui.theme import get_banner_attr, get_current_mode

    is_dark_mode = get_current_mode()
    banner_attr = get_banner_attr(is_dark_mode)
    for i, line in enumerate(BANNER_LINES):
        row = start_row + i
        # Truncate if wider than screen
        truncated_line = line[:width]
        for j, char in enumerate(truncated_line):
            attr = banner_attr
            if animation_engine:
                color_idx = animation_engine.get_color(j, i, is_big=True)
                if color_idx is not None:
                    attr = curses.color_pair(color_idx)

            try:
                stdscr.addstr(row, j, char, attr)  # type: ignore[attr-defined]
            except curses.error:
                pass
    return BANNER_HEIGHT
