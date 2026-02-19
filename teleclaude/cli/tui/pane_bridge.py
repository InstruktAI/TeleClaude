"""Bridge between Textual messages and TmuxPaneManager."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widget import Widget

from teleclaude.cli.tui.messages import (
    DataRefreshed,
    FocusPaneRequest,
    PreviewChanged,
    StickyChanged,
)
from teleclaude.cli.tui.pane_manager import ComputerInfo, TmuxPaneManager

if TYPE_CHECKING:
    from teleclaude.cli.models import ComputerInfo as APIComputerInfo
    from teleclaude.cli.models import SessionInfo


class PaneManagerBridge(Widget):
    """Invisible widget that bridges Textual messages to TmuxPaneManager.

    Listens for PreviewChanged, StickyChanged, and FocusPaneRequest messages
    and translates them into pane_manager.apply_layout() calls.
    No polling. Events only.
    """

    DEFAULT_CSS = """
    PaneManagerBridge {
        display: none;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.pane_manager = TmuxPaneManager()
        self._computers: dict[str, APIComputerInfo] = {}
        self._sessions: list[SessionInfo] = []
        self._preview_session_id: str | None = None
        self._sticky_session_ids: list[str] = []

    def _get_computer_info(self, computer_name: str) -> ComputerInfo | None:
        """Convert API ComputerInfo to pane_manager ComputerInfo."""
        api_info = self._computers.get(computer_name)
        if not api_info:
            return None
        return ComputerInfo(
            name=api_info.name,
            is_local=api_info.is_local,
            user=api_info.user,
            host=api_info.host,
            tmux_binary=api_info.tmux_binary,
        )

    def _apply(self, *, focus: bool = True) -> None:
        """Apply the current layout to the pane manager."""
        self.pane_manager.update_session_catalog(self._sessions)
        self.pane_manager.apply_layout(
            active_session_id=self._preview_session_id,
            sticky_session_ids=self._sticky_session_ids,
            get_computer_info=self._get_computer_info,
            focus=focus,
        )

    def on_data_refreshed(self, message: DataRefreshed) -> None:
        """Update cached data from API refresh."""
        self._computers = {c.name: c for c in message.computers}
        self._sessions = message.sessions
        self.pane_manager.update_session_catalog(self._sessions)

    def on_preview_changed(self, message: PreviewChanged) -> None:
        """Handle preview session change — update active pane."""
        self._preview_session_id = message.session_id
        self._apply()

    def on_sticky_changed(self, message: StickyChanged) -> None:
        """Handle sticky sessions change — rebuild layout."""
        self._sticky_session_ids = message.session_ids
        self._apply()

    def on_focus_pane_request(self, message: FocusPaneRequest) -> None:
        """Handle explicit focus request."""
        self.pane_manager.focus_pane_for_session(message.session_id)

    def reapply_colors(self) -> None:
        """Re-apply agent colors after theme change."""
        self.pane_manager.reapply_agent_colors()

    def cleanup(self) -> None:
        """Clean up all panes on exit."""
        self.pane_manager.cleanup()
