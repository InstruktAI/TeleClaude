"""Configuration view - main config tab."""

from __future__ import annotations

import curses
from typing import TYPE_CHECKING, Callable

from instrukt_ai_logging import get_logger

from teleclaude.cli.models import AgentAvailabilityInfo, ProjectWithTodosInfo, SessionInfo
from teleclaude.cli.models import ComputerInfo as ApiComputerInfo
from teleclaude.cli.tui.config_components.adapters import (
    AIKeysConfigComponent,
    DiscordConfigComponent,
    TelegramConfigComponent,
    WhatsAppConfigComponent,
)
from teleclaude.cli.tui.config_components.base import ConfigComponent
from teleclaude.cli.tui.config_components.environment import EnvironmentConfigComponent
from teleclaude.cli.tui.config_components.notifications import NotificationsConfigComponent
from teleclaude.cli.tui.config_components.people import PeopleConfigComponent
from teleclaude.cli.tui.config_components.validate import ValidateConfigComponent
from teleclaude.cli.tui.controller import TuiController
from teleclaude.cli.tui.pane_manager import TmuxPaneManager
from teleclaude.cli.tui.state import Intent, IntentType, TuiState
from teleclaude.cli.tui.types import CursesWindow, NotificationLevel
from teleclaude.cli.tui.views.base import BaseView

if TYPE_CHECKING:
    from teleclaude.cli.api_client import TelecAPIClient
    from teleclaude.cli.tui.app import FocusContext

logger = get_logger(__name__)


class ConfigurationView(BaseView):
    """View 3: Configuration."""

    SUBTABS = ["adapters", "people", "notifications", "environment", "validate"]
    ADAPTER_TABS = ["telegram", "discord", "ai_keys", "whatsapp"]

    def __init__(
        self,
        api: "TelecAPIClient",
        agent_availability: dict[str, AgentAvailabilityInfo],
        focus: "FocusContext",
        pane_manager: TmuxPaneManager,
        state: TuiState,
        controller: TuiController,
        notify: Callable[[str, NotificationLevel], None] | None = None,
        on_animation_context_change: Callable[[str, str, str, float], None] | None = None,
    ):
        self.api = api
        self.agent_availability = agent_availability
        self.focus = focus
        self.pane_manager = pane_manager
        self.state = state
        self.controller = controller
        self.notify = notify
        self.on_animation_context_change_callback = on_animation_context_change

        # Internal navigation state
        self.active_subtab_idx = 0
        self.active_adapter_idx = 0

        # Initialize components
        # We instantiate them once and reuse them
        self.components: dict[str, ConfigComponent] = {
            "adapters.telegram": TelegramConfigComponent(self),
            "adapters.discord": DiscordConfigComponent(self),
            "adapters.ai_keys": AIKeysConfigComponent(self),
            "adapters.whatsapp": WhatsAppConfigComponent(self),
            "people": PeopleConfigComponent(self),
            "notifications": NotificationsConfigComponent(self),
            "environment": EnvironmentConfigComponent(self),
            "validate": ValidateConfigComponent(self),
        }

        self.flat_items = []  # Required by BaseView but unused
        self.needs_refresh = False  # Required by TelecApp

    # --- ConfigComponentCallback implementation ---

    def on_animation_context_change(self, target: str, section_id: str, state: str, progress: float) -> None:
        if self.on_animation_context_change_callback:
            self.on_animation_context_change_callback(target, section_id, state, progress)

    def request_redraw(self) -> None:
        # TUI loop redraws continuously, so this is implicit
        pass

    # --- Properties ---

    @property
    def active_subtab(self) -> str:
        return self.SUBTABS[self.active_subtab_idx]

    @property
    def current_component(self) -> ConfigComponent:
        if self.active_subtab == "adapters":
            adapter_key = self.ADAPTER_TABS[self.active_adapter_idx]
            return self.components[f"adapters.{adapter_key}"]
        return self.components[self.active_subtab]

    @property
    def selected_index(self) -> int:
        # Required by BaseView/TelecApp interface, though we delegate to components
        return 0

    # --- View Methods ---

    async def refresh(
        self,
        computers: list[ApiComputerInfo],
        projects: list[ProjectWithTodosInfo],
        sessions: list[SessionInfo],
    ) -> None:
        pass

    def rebuild_for_focus(self) -> None:
        if hasattr(self.current_component, "on_focus"):
            self.current_component.on_focus()

    def get_action_bar(self) -> str:
        guided = self.state.config.guided_mode
        if guided:
            return "[Enter] Next Step  [Esc] Exit Guided Mode"
        return "[Tab] Next Tab  [Arrows] Navigate/Edit  [Enter] Edit  [Textual Config tab supports inline env edits]"

    def move_up(self) -> None:
        self.current_component.handle_key(curses.KEY_UP)

    def move_down(self) -> None:
        self.current_component.handle_key(curses.KEY_DOWN)

    def collapse_selected(self) -> bool:
        return False

    def drill_down(self) -> bool:
        return False

    def handle_click(self, row: int, is_double_click: bool = False) -> bool:
        # Mouse support placeholder
        return False

    def handle_enter(self, stdscr: CursesWindow) -> None:
        if self.state.config.guided_mode:
            self._advance_guided_mode()
        else:
            # Let component handle Enter (e.g. edit field)
            # 10 is ENTER
            self.current_component.handle_key(10)

    def handle_key(self, key: int, stdscr: CursesWindow) -> None:
        # Tab handling for main subtabs (unless handled by component or guided mode)
        if not self.state.config.guided_mode:
            if key == 9:  # Tab
                self.active_subtab_idx = (self.active_subtab_idx + 1) % len(self.SUBTABS)
                self.rebuild_for_focus()  # trigger on_focus
                return
            elif key == curses.KEY_BTAB:  # Shift-Tab
                self.active_subtab_idx = (self.active_subtab_idx - 1) % len(self.SUBTABS)
                self.rebuild_for_focus()
                return

            # Left/Right for Adapter switching if on adapters tab
            if self.active_subtab == "adapters":
                if key == curses.KEY_RIGHT:
                    self.active_adapter_idx = (self.active_adapter_idx + 1) % len(self.ADAPTER_TABS)
                    self.rebuild_for_focus()
                    return
                elif key == curses.KEY_LEFT:
                    self.active_adapter_idx = (self.active_adapter_idx - 1) % len(self.ADAPTER_TABS)
                    self.rebuild_for_focus()
                    return

        # Pass to component
        handled = self.current_component.handle_key(key)
        if handled:
            return

        # Guided mode navigation
        if self.state.config.guided_mode:
            if key == 27:  # Esc -> Exit
                self.controller.dispatch(Intent(IntentType.SET_CONFIG_GUIDED_MODE, {"enabled": False}))
                if self.notify:
                    self.notify("Exited guided mode", NotificationLevel.INFO)

    def render(self, stdscr: CursesWindow, row: int, height: int, width: int) -> None:
        try:
            # 1. Render Sub-tabs (Main)
            col = 2
            for i, name in enumerate(self.SUBTABS):
                is_active = i == self.active_subtab_idx
                label = f" {name.upper()} " if is_active else f" {name} "
                attr = curses.A_REVERSE if is_active else curses.A_NORMAL
                stdscr.addstr(row, col, label, attr)
                col += len(label) + 2

            legacy_note = "Legacy view. Inline env editing is available in the Textual Config tab."
            stdscr.addstr(row + 1, 2, legacy_note[: max(0, width - 4)], curses.A_DIM)

            row += 3
            height -= 3

            # 2. Render Adapter Tabs (if active)
            if self.active_subtab == "adapters":
                col = 2
                stdscr.addstr(row, 0, "Adapters: ", curses.A_DIM)
                col += 10
                for i, name in enumerate(self.ADAPTER_TABS):
                    is_active = i == self.active_adapter_idx
                    label = f"[{name}]" if is_active else f" {name} "
                    attr = curses.A_BOLD if is_active else curses.A_DIM
                    stdscr.addstr(row, col, label, attr)
                    col += len(label) + 1
                row += 2
                height -= 2

            # 3. Guided Mode Progress
            if self.state.config.guided_mode:
                step_info = f"GUIDED MODE: Step {self.active_subtab_idx + 1}/{len(self.SUBTABS)}"
                stdscr.addstr(
                    row - 2 if self.active_subtab == "adapters" else row,
                    width - len(step_info) - 2,
                    step_info,
                    curses.A_REVERSE | curses.A_BOLD,
                )

            # 4. Render Active Component
            self.current_component.render(stdscr, row, height, width)

            # Update animation context
            self.current_component.notify_animation_change()

        except curses.error:
            pass

    def get_render_lines(self, width: int, height: int) -> list[str]:
        return [f"Config: {self.active_subtab}"]

    def _advance_guided_mode(self) -> None:
        # Logic to move to next step in guided mode
        # If in adapters, maybe iterate through adapters first?
        # Requirement FR-4.2: Adapters -> People -> Notifications -> Environment -> Validate

        if self.active_subtab == "adapters":
            if self.active_adapter_idx < len(self.ADAPTER_TABS) - 1:
                self.active_adapter_idx += 1
            else:
                self.active_subtab_idx += 1
                self.active_adapter_idx = 0
        elif self.active_subtab_idx < len(self.SUBTABS) - 1:
            self.active_subtab_idx += 1
        else:
            # Finished
            self.controller.dispatch(Intent(IntentType.SET_CONFIG_GUIDED_MODE, {"enabled": False}))
            if self.notify:
                self.notify("Configuration completed!", NotificationLevel.SUCCESS)

        self.rebuild_for_focus()
