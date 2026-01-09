"""Tab bar widget for view switching."""

import curses


class TabBar:
    """Tab bar showing [1] Sessions  [2] Preparation."""

    def __init__(self) -> None:
        """Initialize tab bar."""
        self.active = 1

    def set_active(self, view_num: int) -> None:
        """Set active view.

        Args:
            view_num: View number (1 or 2)
        """
        self.active = view_num

    def render(self, stdscr: object, row: int, width: int) -> None:
        """Render tab bar.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            width: Screen width
        """
        # Format: ─ [1] Sessions  [2] Preparation ────────────
        sessions_attr = curses.A_BOLD if self.active == 1 else 0
        prep_attr = curses.A_BOLD if self.active == 2 else 0

        stdscr.addstr(row, 0, "─ ")  # type: ignore[attr-defined]
        stdscr.addstr(row, 2, "[1] Sessions", sessions_attr)  # type: ignore[attr-defined]
        stdscr.addstr(row, 16, "  ")  # type: ignore[attr-defined]
        stdscr.addstr(row, 18, "[2] Preparation", prep_attr)  # type: ignore[attr-defined]
        stdscr.addstr(row, 35, " " + "─" * (width - 36))  # type: ignore[attr-defined]
