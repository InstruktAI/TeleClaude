"""Configuration view - main config tab."""

from __future__ import annotations

import curses
from typing import TYPE_CHECKING, Callable

from instrukt_ai_logging import get_logger

from teleclaude.cli.models import AgentAvailabilityInfo, ProjectWithTodosInfo, SessionInfo
from teleclaude.cli.models import ComputerInfo as ApiComputerInfo
from teleclaude.cli.tui.controller import TuiController
from teleclaude.cli.tui.pane_manager import TmuxPaneManager
from teleclaude.cli.tui.state import TuiState
from teleclaude.cli.tui.types import NotificationLevel
from teleclaude.cli.tui.views.base import BaseView

if TYPE_CHECKING:
    from teleclaude.cli.api_client import TelecAPIClient
    from teleclaude.cli.tui.app import FocusContext
    from teleclaude.cli.tui.types import CursesWindow

logger = get_logger(__name__)


class ConfigurationView(BaseView):
    """View 3: Configuration."""

    SUBTABS = ["adapters", "people", "notifications", "environment", "validate"]

    def __init__(
        self,
        api: "TelecAPIClient",
        agent_availability: dict[str, AgentAvailabilityInfo],
        focus: "FocusContext",
        pane_manager: TmuxPaneManager,
        state: TuiState,
        controller: TuiController,
        notify: Callable[[str, NotificationLevel], None] | None = None,
    ):
        self.api = api
        self.agent_availability = agent_availability
        self.focus = focus
        self.pane_manager = pane_manager
        self.state = state
        self.controller = controller
        self.notify = notify

        # Internal state (until moved to TuiState)
        self.active_subtab_idx = 0

        # Required by BaseView/App assumption but unused for now
        self.flat_items = []
        self.selected_index = 0

    @property
    def active_subtab(self) -> str:
        return self.SUBTABS[self.active_subtab_idx]

    async def refresh(
        self,
        computers: list[ApiComputerInfo],
        projects: list[ProjectWithTodosInfo],
        sessions: list[SessionInfo],
    ) -> None:
        """Refresh view data."""
        pass

    def rebuild_for_focus(self) -> None:
        """Rebuild view based on focus context."""
        pass

    def get_action_bar(self) -> str:
        return "[Tab] Next Section  [Enter] Edit"

    def move_up(self) -> None:
        pass

    def move_down(self) -> None:
        pass

    def handle_key(self, key: int, stdscr: "CursesWindow") -> None:
        if key == 9:  # Tab
            self.active_subtab_idx = (self.active_subtab_idx + 1) % len(self.SUBTABS)
            logger.debug("Switched subtab to %s", self.active_subtab)
        # Shift-Tab is often KEY_BTAB (353) or similar
        elif key == curses.KEY_BTAB:
            self.active_subtab_idx = (self.active_subtab_idx - 1) % len(self.SUBTABS)
            logger.debug("Switched subtab back to %s", self.active_subtab)

    def render(self, stdscr: "CursesWindow", row: int, height: int, width: int) -> None:
        try:
            # Render Sub-tabs
            col = 2
            for i, name in enumerate(self.SUBTABS):
                label = f" {name.upper()} " if i == self.active_subtab_idx else f" {name} "
                attr = curses.A_REVERSE if i == self.active_subtab_idx else curses.A_NORMAL
                stdscr.addstr(row, col, label, attr)
                col += len(label) + 2

            # Render content placeholder
            stdscr.addstr(row + 2, 2, f"Configuration for: {self.active_subtab}", curses.A_BOLD)
            stdscr.addstr(row + 4, 2, "(Coming soon in Phase 4)")

            # Animation target registration (Phase 2 integration)
            # This should happen in app.py or controller, but here we can ensure context
            # We assume app handles "config_banner" target registration if needed.

        except curses.error:
            pass

    def get_render_lines(self, width: int, height: int) -> list[str]:
        return [f"Config: {self.active_subtab}"]
