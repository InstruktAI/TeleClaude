"""People config component."""

from __future__ import annotations

import curses
from typing import TYPE_CHECKING

from teleclaude.cli.config_handlers import list_people
from teleclaude.cli.tui.config_components.base import ConfigComponent, ConfigComponentCallback

if TYPE_CHECKING:
    from teleclaude.cli.tui.types import CursesWindow
    from teleclaude.config.schema import PersonEntry


class PeopleConfigComponent(ConfigComponent):
    """Component for managing people."""

    def __init__(self, callback: ConfigComponentCallback) -> None:
        super().__init__(callback)
        self.people: list[PersonEntry] = []
        self.selected_index = 0
        self.scroll_offset = 0

    def get_section_id(self) -> str:
        return "people"

    def get_animation_state(self) -> str:
        return "idle"

    def render(self, stdscr: CursesWindow, start_row: int, height: int, width: int) -> None:
        stdscr.addstr(start_row, 0, "People Configuration", curses.A_BOLD)

        row = start_row + 2

        if not self.people:
            stdscr.addstr(row, 0, "(No people configured)", curses.A_DIM)
            return

        for i, person in enumerate(self.people):
            if i < self.scroll_offset:
                continue
            if row >= start_row + height:
                break

            is_selected = i == self.selected_index
            attr = curses.A_REVERSE if is_selected else 0

            line = f"{person.name} ({person.role})"
            if person.email:
                line += f" <{person.email}>"

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
            if not self.people:
                return True
            max_idx = len(self.people) - 1
            self.selected_index = min(max_idx, self.selected_index + 1)
            # Simple scroll tracking
            if self.selected_index > self.scroll_offset + 5:
                self.scroll_offset += 1
            self.notify_animation_change()
            return True
        return False

    def on_focus(self) -> None:
        # Refresh list on focus in case it changed
        self.people = list_people()
        self.selected_index = min(self.selected_index, max(0, len(self.people) - 1))
