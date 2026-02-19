"""Tab bar widget for view switching."""

import curses

from teleclaude.cli.tui.theme import get_tab_line_attr


class TabBar:
    """Browser-style tab bar with boxed active tab."""

    TABS = [
        (1, "[1] AI Sessions"),
        (2, "[2] Work Preparation"),
        (3, "[3] Jobs"),
        (4, "[4] Configuration"),
    ]
    HEIGHT = 3  # Tab bar spans 3 rows

    def __init__(self) -> None:
        """Initialize tab bar."""
        self.active = 1
        # Click regions: list of (col_start, col_end, view_num) built during render
        self._click_regions: list[tuple[int, int, int]] = []
        self._row_start: int = 0  # Starting row of tab bar

    def set_active(self, view_num: int) -> None:
        """Set active view.

        Args:
            view_num: View number (1 or 2)
        """
        self.active = view_num

    def render(self, stdscr: object, row: int, width: int, logo_width: int | None = None) -> None:
        """Render browser-style tab bar (3 rows).

        Active tab has box with open bottom, inactive is plain text.

        Args:
            stdscr: Curses screen object
            row: Starting row to render at
            width: Screen width
            logo_width: Optional width of logo at right edge; if provided, bottom line stops before it
        """
        # Store row start for click detection
        self._row_start = row
        self._click_regions.clear()

        # Calculate tab positions and labels
        tab_positions: list[tuple[int, int, str, bool]] = []  # (col, width, label, is_active)
        col = 1  # Start with 1 char margin
        for view_num, label in self.TABS:
            is_active = self.active == view_num
            padded_label = f" {label} "  # 1 space padding each side
            tab_width = len(padded_label)
            tab_positions.append((col, tab_width, padded_label, is_active))
            # Store click region: from col to col + tab_width + 1 (including borders)
            self._click_regions.append((col, col + tab_width + 2, view_num))
            col += tab_width + 2  # +2 for spacing between tabs

        # Row 1: Top border of active tab only
        # Box spans: ╭ at c, ─ from c+1 to c+w, ╮ at c+w+1 (to align with │ borders below)
        line_attr = get_tab_line_attr()
        line1 = [" "] * width
        for c, w, _, is_active in tab_positions:
            if is_active:
                line1[c] = "╭"
                for i in range(1, w + 1):
                    if c + i < width:
                        line1[c + i] = "─"
                if c + w + 1 < width:
                    line1[c + w + 1] = "╮"
        stdscr.addstr(row, 0, "".join(line1)[:width], line_attr)  # type: ignore[attr-defined]

        # Row 2: Tab labels with side borders for active
        line2 = [" "] * width
        for c, w, label, is_active in tab_positions:
            if is_active:
                line2[c] = "│"
                if c + w + 1 < width:
                    line2[c + w + 1] = "│"
            else:
                # Inactive label rendered inline
                for i, ch in enumerate(label):
                    if c + 1 + i < width:
                        line2[c + 1 + i] = ch
        stdscr.addstr(row + 1, 0, "".join(line2)[:width])  # type: ignore[attr-defined]

        # Render active tab label with BOLD
        for c, _, label, is_active in tab_positions:
            if is_active:
                stdscr.addstr(row + 1, c + 1, label, curses.A_BOLD)  # type: ignore[attr-defined]
                stdscr.addstr(row + 1, c, "│", line_attr)  # type: ignore[attr-defined]
                if c + len(label) + 1 < width:
                    stdscr.addstr(row + 1, c + len(label) + 1, "│", line_attr)  # type: ignore[attr-defined]

        # Row 3: Bottom line with breaks at active tab corners
        # If logo_width is provided, stop the line before the logo with 1-char gap
        line_end = width if logo_width is None else width - logo_width - 1
        line3 = ["─"] * width
        for c, w, _, is_active in tab_positions:
            if is_active:
                line3[c] = "┴"
                for i in range(1, w + 1):
                    if c + i < width:
                        line3[c + i] = " "
                if c + w + 1 < width:
                    line3[c + w + 1] = "┴"
        # Render only up to line_end, rest becomes spaces
        line3_str = "".join(line3)[:line_end] + " " * (width - line_end)
        stdscr.addstr(row + 2, 0, line3_str[:width], line_attr)  # type: ignore[attr-defined]

    def handle_click(self, screen_row: int, screen_col: int) -> int | None:
        """Handle mouse click, return view number if tab was clicked.

        Args:
            screen_row: The screen row that was clicked
            screen_col: The screen column that was clicked

        Returns:
            View number (1 or 2) if a tab was clicked, None otherwise
        """
        # Check if click is within tab bar rows
        if not (self._row_start <= screen_row < self._row_start + self.HEIGHT):
            return None

        # Check which tab was clicked
        for col_start, col_end, view_num in self._click_regions:
            if col_start <= screen_col < col_end:
                return view_num

        return None
