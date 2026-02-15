"""Environment config component."""

from __future__ import annotations

import curses
from typing import TYPE_CHECKING, Any

from teleclaude.cli.config_handlers import check_env_vars
from teleclaude.cli.tui.config_components.base import ConfigComponent

if TYPE_CHECKING:
    from teleclaude.cli.tui.types import CursesWindow


class EnvironmentConfigComponent(ConfigComponent):
    """Component for displaying environment variable status."""

    def __init__(self, callback: Any) -> None:
        super().__init__(callback)
        self.env_status = check_env_vars()
        self.selected_index = 0
        self.scroll_offset = 0

    def get_section_id(self) -> str:
        return "environment"

    def get_animation_state(self) -> str:
        return "idle"

    def render(self, stdscr: CursesWindow, start_row: int, height: int, width: int) -> None:
        stdscr.addstr(start_row, 0, "Environment Variables", curses.A_BOLD)

        row = start_row + 2

        for i, status in enumerate(self.env_status):
            if i < self.scroll_offset:
                continue
            if row >= start_row + height:
                break

            is_selected = i == self.selected_index
            attr = curses.A_REVERSE if is_selected else 0

            mark = "✅" if status.is_set else "❌"
            line = f"{mark} {status.info.name} ({status.info.adapter})"

            stdscr.addstr(row, 0, line[:width], attr)
            row += 1

    def handle_key(self, key: int) -> bool:
        if key == curses.KEY_UP:
            self.selected_index = max(0, self.selected_index - 1)
            if self.selected_index < self.scroll_offset:
                self.scroll_offset = self.selected_index
            self.notify_animation_change()
            return True
        elif key == curses.KEY_DOWN:
            max_idx = len(self.env_status) - 1
            self.selected_index = min(max_idx, self.selected_index + 1)
            if self.selected_index > self.scroll_offset + 5:
                self.scroll_offset += 1
            self.notify_animation_change()
            return True
        return False

    def on_focus(self) -> None:
        self.env_status = check_env_vars()
