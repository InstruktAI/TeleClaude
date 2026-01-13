"""ASCII banner widget."""

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
    from teleclaude.cli.tui.theme import get_banner_attr, get_current_mode

    is_dark_mode = get_current_mode()
    banner_attr = get_banner_attr(is_dark_mode)
    for i, line in enumerate(BANNER_LINES):
        row = start_row + i
        # Truncate if wider than screen
        stdscr.addstr(row, 0, line[:width], banner_attr)  # type: ignore[attr-defined]
    return BANNER_HEIGHT
