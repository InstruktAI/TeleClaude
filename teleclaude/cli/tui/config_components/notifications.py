"""Notifications config component."""

from __future__ import annotations

import curses
from typing import TYPE_CHECKING, Any

from teleclaude.cli.tui.config_components.base import ConfigComponent

if TYPE_CHECKING:
    from teleclaude.cli.tui.types import CursesWindow


class NotificationsConfigComponent(ConfigComponent):
    """Component for notification settings."""

    def __init__(self, callback: Any) -> None:
        super().__init__(callback)
        # Assuming current user context or default user?
        # Ideally this component should know WHICH user config it's editing.
        # But for now let's assume global or prompt user?
        # The requirements imply global configuration context or active user context.
        # Since config_handlers has load_person_config(name), we need a name.
        # Let's assume we edit the first person found or have a way to select.
        # For simplicity, let's just show a placeholder if no user is selected or passed.
        self.person_name = None
        self.config = None

    def get_section_id(self) -> str:
        return "notifications"

    def get_animation_state(self) -> str:
        return "idle"

    def render(self, stdscr: CursesWindow, start_row: int, height: int, width: int) -> None:
        stdscr.addstr(start_row, 0, "Notifications Configuration", curses.A_BOLD)
        stdscr.addstr(start_row + 2, 0, "(Not implemented yet - requires user selection)", curses.A_DIM)

    def handle_key(self, key: int) -> bool:
        return False
