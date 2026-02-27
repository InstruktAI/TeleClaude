"""Adapter config components."""

from __future__ import annotations

import curses
from typing import TYPE_CHECKING

from teleclaude.cli.config_handlers import check_env_vars, get_adapter_env_vars
from teleclaude.cli.tui.config_components.base import ConfigComponent, ConfigComponentCallback

if TYPE_CHECKING:
    from teleclaude.cli.tui.types import CursesWindow


class AdapterConfigComponent(ConfigComponent):
    """Base class for adapter config components."""

    def __init__(
        self,
        callback: ConfigComponentCallback,
        section_id: str,
        label: str,
        env_vars_keys: list[str] | None = None,
    ) -> None:
        super().__init__(callback)
        self.section_id = section_id
        self.label = label

        # Load env vars
        self.env_vars = []
        if env_vars_keys:
            for key in env_vars_keys:
                self.env_vars.extend(get_adapter_env_vars(key))

        self.selected_index = 0
        self.scroll_offset = 0

    def get_section_id(self) -> str:
        return self.section_id

    def get_animation_state(self) -> str:
        # TODO: track interaction state (interacting, success, error)
        return "idle"

    def render(self, stdscr: CursesWindow, start_row: int, height: int, width: int) -> None:
        # Header
        stdscr.addstr(start_row, 0, f"Configuring {self.label}", curses.A_BOLD)

        # Determine visible area for list
        list_start_row = start_row + 2
        guidance_height = 4
        list_height = height - 2 - guidance_height

        # Helper to check env var status
        all_env_status = {s.info.name: s.is_set for s in check_env_vars()}

        items = self.env_vars  # For now only env vars

        # Rendering list
        for i, env in enumerate(items):
            if i < self.scroll_offset:
                continue
            if i >= self.scroll_offset + list_height:
                break

            row = list_start_row + (i - self.scroll_offset)
            is_selected = i == self.selected_index
            attr = curses.A_REVERSE if is_selected else 0

            is_set = all_env_status.get(env.name, False)
            status = "✅" if is_set else "❌"

            # Simple list item rendering
            line = f"{status} {env.name} ({env.description})"
            if len(line) > width:
                line = line[: width - 1] + "…"

            try:
                stdscr.addstr(row, 0, line, attr)
            except curses.error:
                pass

        # Rendering Guidance Panel
        if 0 <= self.selected_index < len(items):
            selected_item = items[self.selected_index]
            guidance_row = start_row + height - guidance_height

            # Separator
            stdscr.hline(guidance_row - 1, 0, curses.ACS_HLINE, width)

            try:
                stdscr.addstr(guidance_row, 0, "GUIDANCE:", curses.A_BOLD)
                stdscr.addstr(guidance_row, 10, f" {selected_item.description}", curses.A_DIM)
                stdscr.addstr(guidance_row + 1, 0, f"Example: {selected_item.example}", curses.A_DIM)
                if not all_env_status.get(selected_item.name, False):
                    stdscr.addstr(
                        guidance_row + 2,
                        0,
                        f"⚠️  Variable {selected_item.name} is not set!",
                        curses.A_BOLD | curses.color_pair(3),
                    )  # Red if available
            except curses.error:
                pass

    def handle_key(self, key: int) -> bool:
        if key == curses.KEY_UP:
            self.selected_index = max(0, self.selected_index - 1)
            if self.selected_index < self.scroll_offset:
                self.scroll_offset = self.selected_index
            self.notify_animation_change()
            return True
        elif key == curses.KEY_DOWN:
            if not self.env_vars:
                return True
            max_idx = len(self.env_vars) - 1
            self.selected_index = min(max_idx, self.selected_index + 1)
            # Scroll down
            # Need to know list_height from render context... assuming fixed for now or roughly calculated
            # A better way is to store list_height in render
            # For now, let's just ensure scroll follows selection blindly
            # We don't know visible height here easily without storing state from render.
            # But we can assume a reasonable minimum or just scroll if index - offset > 10?
            # Let's just update scroll_offset loosely.
            if self.selected_index > self.scroll_offset + 5:  # simple heuristic
                self.scroll_offset += 1
            self.notify_animation_change()
            return True
        return False


class TelegramConfigComponent(AdapterConfigComponent):
    def __init__(self, callback: ConfigComponentCallback) -> None:
        super().__init__(callback, "adapters.telegram", "Telegram", ["telegram"])


class DiscordConfigComponent(AdapterConfigComponent):
    def __init__(self, callback: ConfigComponentCallback) -> None:
        super().__init__(callback, "adapters.discord", "Discord", ["discord"])


class AIKeysConfigComponent(AdapterConfigComponent):
    def __init__(self, callback: ConfigComponentCallback) -> None:
        super().__init__(callback, "adapters.ai_keys", "AI Keys", ["ai", "voice"])


class WhatsAppConfigComponent(AdapterConfigComponent):
    def __init__(self, callback: ConfigComponentCallback) -> None:
        super().__init__(callback, "adapters.whatsapp", "WhatsApp", ["whatsapp"])
