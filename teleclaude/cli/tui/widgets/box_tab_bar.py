"""Box-drawing tab bar matching old curses TUI style."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.theme import CONNECTOR_COLOR, NEUTRAL_HIGHLIGHT_COLOR, NEUTRAL_MUTED_COLOR


class BoxTabBar(TelecMixin, Widget):
    """3-row tab bar with box-drawing characters.

    Active tab rendered with open-bottom box:
      ╭──────────────────╮
      │ [1] AI Sessions  │  [2] Work Preparation   [3] Jobs   [4] Configuration
    ──┴                  ┴───────────────────────────────────────────────────────
    """

    TABS = [
        ("sessions", "[1] AI Sessions"),
        ("preparation", "[2] Work Preparation"),
        ("jobs", "[3] Jobs"),
        ("config", "[4] Configuration"),
    ]

    DEFAULT_CSS = """
    BoxTabBar {
        width: 100%;
        height: 3;
    }
    """

    active_tab = reactive("sessions")

    class TabClicked(Message):
        """Posted when a tab is clicked."""

        def __init__(self, tab_id: str) -> None:
            super().__init__()
            self.tab_id = tab_id

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._click_regions: list[tuple[int, int, str]] = []

    def render(self) -> Group:
        width = self.size.width or 80
        line_color = CONNECTOR_COLOR

        # Calculate tab positions: (col, width, padded_label, is_active, tab_id)
        tabs: list[tuple[int, int, str, bool, str]] = []
        col = 1  # 1 char left margin
        for tab_id, label in self.TABS:
            is_active = self.active_tab == tab_id
            padded = f" {label} "
            w = len(padded)
            tabs.append((col, w, padded, is_active, tab_id))
            col += w + 2  # +2 for border chars

        # Store click regions for mouse handling
        self._click_regions = [(c, c + w + 2, tid) for c, w, _, _, tid in tabs]

        # Row 1: Top border of tabs (active = solid, inactive = ghost)
        row1 = Text()
        pos = 0
        from teleclaude.cli.tui.theme import NEUTRAL_SUBTLE_COLOR
        ghost_color = NEUTRAL_SUBTLE_COLOR

        for c, w, _, is_active, _ in tabs:
            if pos < c:
                row1.append(" " * (c - pos))
                pos = c
            if is_active:
                row1.append("\u256d", style=line_color)
                row1.append("\u2500" * w, style=line_color)
                row1.append("\u256e", style=line_color)
            else:
                row1.append("\u256d", style=ghost_color)
                row1.append("\u2500" * w, style=ghost_color)
                row1.append("\u256e", style=ghost_color)
            pos = c + w + 2
        if pos < width:
            row1.append(" " * (width - pos))

        # Row 2: Tab labels with side borders
        row2 = Text()
        pos = 0
        for c, w, label, is_active, _ in tabs:
            if pos < c:
                row2.append(" " * (c - pos))
                pos = c
            if is_active:
                row2.append("\u2502", style=line_color)
                row2.append(label, style=f"bold {NEUTRAL_HIGHLIGHT_COLOR}")
                row2.append("\u2502", style=line_color)
            else:
                row2.append("\u2502", style=ghost_color)
                row2.append(label, style=NEUTRAL_MUTED_COLOR)
                row2.append("\u2502", style=ghost_color)
            pos = c + w + 2
        if pos < width:
            row2.append(" " * (width - pos))

        # Row 3: Continuous bottom line with connectors
        row3 = Text()
        pos = 0
        for c, w, _, is_active, _ in tabs:
            if pos < c:
                row3.append("\u2500" * (c - pos), style=line_color)
                pos = c
            if is_active:
                row3.append("\u2534", style=line_color)
                row3.append(" " * w)
                row3.append("\u2534", style=line_color)
            else:
                row3.append("\u2534", style=ghost_color)
                row3.append("\u2500" * w, style=ghost_color)
                row3.append("\u2534", style=ghost_color)
            pos = c + w + 2
        if pos < width:
            row3.append("\u2500" * (width - pos), style=line_color)

        return Group(row1, row2, row3)

    def on_click(self, event: object) -> None:
        """Handle mouse click to switch tabs."""
        x = getattr(event, "x", -1)
        for col_start, col_end, tab_id in self._click_regions:
            if col_start <= x < col_end:
                self.post_message(self.TabClicked(tab_id))
                break

    def watch_active_tab(self, _value: str) -> None:
        self.refresh()
