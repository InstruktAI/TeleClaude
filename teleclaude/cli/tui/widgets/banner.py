"""ASCII banner widget."""

import curses

BANNER_LINES = [
    "████████╗███████╗██╗     ███████╗ ██████╗██╗      █████╗ ██╗   ██╗██████╗ ███████╗",
    "╚══██╔══╝██╔════╝██║     ██╔════╝██╔════╝██║     ██╔══██╗██║   ██║██╔══██╗██╔════╝",
    "   ██║   █████╗  ██║     █████╗  ██║     ██║     ███████║██║   ██║██║  ██║█████╗  ",
    "   ██║   ██╔══╝  ██║     ██╔══╝  ██║     ██║     ██╔══██║██║   ██║██║  ██║██╔══╝  ",
    "   ██║   ███████╗███████╗███████╗╚██████╗███████╗██║  ██║╚██████╔╝██████╔╝███████╗",
    "   ╚═╝   ╚══════╝╚══════╝╚══════╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝",
]

BANNER_HEIGHT = len(BANNER_LINES)


def render_banner(stdscr: object, start_row: int, width: int) -> int:
    """Render ASCII banner.

    Args:
        stdscr: Curses screen object
        start_row: Starting row
        width: Screen width

    Returns:
        Number of rows used
    """
    for i, line in enumerate(BANNER_LINES):
        row = start_row + i
        # Truncate if wider than screen
        stdscr.addstr(row, 0, line[:width], curses.A_BOLD)  # type: ignore[attr-defined]
    return BANNER_HEIGHT
