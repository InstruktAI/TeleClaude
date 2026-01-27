"""TUI state controller and layout derivation.

Required reads:
- @docs/project/architecture/tui-state-layout.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from instrukt_ai_logging import get_logger

from teleclaude.cli.models import SessionInfo
from teleclaude.cli.tui.pane_manager import ComputerInfo, TmuxPaneManager
from teleclaude.cli.tui.state import DocPreviewState, DocStickyInfo, Intent, IntentType, TuiState, reduce_state

logger = get_logger(__name__)


@dataclass(frozen=True)
class LayoutState:
    """Derived pane layout inputs."""

    active_session_id: str | None
    child_session_id: str | None
    sticky_session_ids: list[str]
    active_doc_preview: DocPreviewState | None
    sticky_doc_previews: list[DocStickyInfo]


class TuiController:
    """Central controller for TUI state and layout."""

    def __init__(
        self,
        state: TuiState,
        pane_manager: TmuxPaneManager,
        get_computer_info: Callable[[str], ComputerInfo | None],
    ) -> None:
        self.state = state
        self.pane_manager = pane_manager
        self._get_computer_info = get_computer_info
        self._sessions: list[SessionInfo] = []
        self._last_layout: LayoutState | None = None

    def update_sessions(self, sessions: list[SessionInfo]) -> None:
        """Update session catalog used for layout derivation."""
        self._sessions = sessions

    def dispatch(self, intent: Intent) -> None:
        """Apply intent to state and update layout if needed."""
        if intent.type is IntentType.SYNC_SESSIONS:
            before_preview = self.state.sessions.preview
            before_sticky = list(self.state.sessions.sticky_sessions)
            reduce_state(self.state, intent)
            if self.state.sessions.preview != before_preview or self.state.sessions.sticky_sessions != before_sticky:
                self.apply_layout(focus=False)
            return
        reduce_state(self.state, intent)
        if intent.type in {
            IntentType.SET_PREVIEW,
            IntentType.CLEAR_PREVIEW,
            IntentType.TOGGLE_STICKY,
            IntentType.SET_PREP_PREVIEW,
            IntentType.CLEAR_PREP_PREVIEW,
            IntentType.TOGGLE_PREP_STICKY,
        }:
            self.apply_layout(focus=False)

    def apply_layout(self, *, focus: bool = False) -> None:
        """Apply pane layout derived from current state."""
        if not self.pane_manager.is_available:
            return
        layout = self._derive_layout()
        if not focus and self._last_layout == layout:
            return
        self._last_layout = layout
        self.pane_manager.apply_layout(
            active_session_id=layout.active_session_id,
            sticky_session_ids=layout.sticky_session_ids,
            child_session_id=layout.child_session_id,
            get_computer_info=self._get_computer_info,
            active_doc_preview=layout.active_doc_preview,
            sticky_doc_previews=layout.sticky_doc_previews,
            focus=focus,
        )

    def _derive_layout(self) -> LayoutState:
        preview = self.state.sessions.preview
        active_session_id = preview.session_id if preview else None
        child_session_id = None
        if preview and preview.show_child:
            child_session_id = self._find_child_session_id(preview.session_id)
        sticky_session_ids = [s.session_id for s in self.state.sessions.sticky_sessions]
        active_doc_preview = self.state.preparation.preview
        sticky_doc_previews = list(self.state.preparation.sticky_previews)
        return LayoutState(
            active_session_id=active_session_id,
            child_session_id=child_session_id,
            sticky_session_ids=sticky_session_ids,
            active_doc_preview=active_doc_preview,
            sticky_doc_previews=sticky_doc_previews,
        )

    def _find_child_session_id(self, parent_session_id: str) -> str | None:
        for sess in self._sessions:
            if sess.initiator_session_id == parent_session_id:
                return sess.session_id
        return None
