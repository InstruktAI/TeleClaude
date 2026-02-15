"""Validation config component."""

from __future__ import annotations

import curses
from typing import TYPE_CHECKING

from teleclaude.cli.config_handlers import validate_all
from teleclaude.cli.tui.config_components.base import ConfigComponent, ConfigComponentCallback

if TYPE_CHECKING:
    from teleclaude.cli.tui.types import CursesWindow


class ValidateConfigComponent(ConfigComponent):
    """Component for validating configuration."""

    def __init__(self, callback: ConfigComponentCallback) -> None:
        super().__init__(callback)
        self.results = []
        self.validating = False
        self.selected_index = 0
        self.scroll_offset = 0

    def get_section_id(self) -> str:
        return "validate"

    def get_animation_state(self) -> str:
        if self.validating:
            return "interacting"
        if not self.results:
            return "idle"
        all_passed = all(r.passed for r in self.results)
        return "success" if all_passed else "error"

    def get_progress(self) -> float:
        if not self.results:
            return 0.0
        passed = sum(1 for r in self.results if r.passed)
        return passed / len(self.results)

    def render(self, stdscr: CursesWindow, start_row: int, height: int, width: int) -> None:
        stdscr.addstr(start_row, 0, "Configuration Validation", curses.A_BOLD)

        if self.validating:
            stdscr.addstr(start_row + 2, 0, "Validating... Please wait.", curses.A_DIM | curses.A_BLINK)
            return

        if not self.results:
            stdscr.addstr(start_row + 2, 0, "Press Enter to run validation.", curses.A_DIM)
            return

        row = start_row + 2

        for i, result in enumerate(self.results):
            if i < self.scroll_offset:
                continue
            if row >= start_row + height:
                break

            is_selected = i == self.selected_index
            attr = curses.A_REVERSE if is_selected else 0

            mark = "✅" if result.passed else "❌"
            line = f"{mark} {result.area}"

            stdscr.addstr(row, 0, line[:width], attr)
            row += 1

            if is_selected and not result.passed:
                # Show errors
                for err in result.errors:
                    if row >= start_row + height:
                        break
                    stdscr.addstr(row, 4, f"Error: {err}", curses.A_DIM)  # Red?
                    row += 1
                for sug in result.suggestions:
                    if row >= start_row + height:
                        break
                    stdscr.addstr(row, 4, f"Tip: {sug}", curses.A_DIM)
                    row += 1

    def handle_key(self, key: int) -> bool:
        if key == 10:  # Enter
            self.run_validation()
            return True
        elif key == curses.KEY_UP:
            self.selected_index = max(0, self.selected_index - 1)
            if self.selected_index < self.scroll_offset:
                self.scroll_offset = self.selected_index
            self.notify_animation_change()
            return True
        elif key == curses.KEY_DOWN:
            if not self.results:
                return True
            max_idx = len(self.results) - 1
            self.selected_index = min(max_idx, self.selected_index + 1)
            if self.selected_index > self.scroll_offset + 5:
                self.scroll_offset += 1
            self.notify_animation_change()
            return True
        return False

    def run_validation(self) -> None:
        self.validating = True
        self.notify_animation_change()
        # TODO: Run in background thread if slow?
        # For now, synchronous is fine as handlers are fast
        try:
            self.results = validate_all()
        finally:
            self.validating = False
            self.notify_animation_change()

    def on_focus(self) -> None:
        # Auto-run validation on focus? Or manual?
        # Manual is safer for animation demonstration.
        pass
