"""TUI state controller and layout derivation.

Required reads:
- @docs/project/design/tui-state-layout.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from instrukt_ai_logging import get_logger

from teleclaude.cli.models import SessionInfo
from teleclaude.cli.tui.pane_manager import ComputerInfo, TmuxPaneManager
from teleclaude.cli.tui.state import DocPreviewState, DocStickyInfo, Intent, IntentType, TuiState, reduce_state
from teleclaude.cli.tui.state_store import save_sticky_state

logger = get_logger(__name__)


@dataclass(frozen=True)
class LayoutState:
    """Derived pane layout inputs."""

    active_session_id: str | None
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
        self._layout_pending = False

    def update_sessions(self, sessions: list[SessionInfo]) -> None:
        """Update session catalog used for layout derivation."""
        self._sessions = sessions

    def _layout_inputs(self) -> tuple[object, ...]:
        preview = self.state.sessions.preview
        preview_key = preview.session_id if preview else None
        sticky_key = tuple(s.session_id for s in self.state.sessions.sticky_sessions)
        prep_preview = self.state.preparation.preview
        prep_preview_key = (prep_preview.doc_id, prep_preview.command, prep_preview.title) if prep_preview else None
        prep_sticky_key = tuple((d.doc_id, d.command, d.title) for d in self.state.preparation.sticky_previews)
        return (preview_key, sticky_key, prep_preview_key, prep_sticky_key)

    def _sticky_inputs(self) -> tuple[object, ...]:
        sticky_key = tuple(s.session_id for s in self.state.sessions.sticky_sessions)
        prep_sticky_key = tuple((d.doc_id, d.command, d.title) for d in self.state.preparation.sticky_previews)
        return (sticky_key, prep_sticky_key)

    def dispatch(self, intent: Intent, *, defer_layout: bool = False) -> None:
        """Apply intent to state and update layout if needed."""
        _ = defer_layout
        layout_intents = {
            IntentType.SYNC_SESSIONS,
            IntentType.SET_PREVIEW,
            IntentType.CLEAR_PREVIEW,
            IntentType.TOGGLE_STICKY,
            IntentType.SET_PREP_PREVIEW,
            IntentType.CLEAR_PREP_PREVIEW,
            IntentType.TOGGLE_PREP_STICKY,
        }
        before_layout = self._layout_inputs() if intent.type in layout_intents else None
        before_sticky = self._sticky_inputs() if intent.type in layout_intents else None

        if intent.type is IntentType.SYNC_SESSIONS:
            reduce_state(self.state, intent)
            after_layout = self._layout_inputs()
            if after_layout == before_layout:
                return
            # Only persist if sticky sessions changed (not preview — preview
            # wipes from SYNC are cleanup, not user intent).
            if self._sticky_inputs() != before_sticky:
                save_sticky_state(self.state)
            return
        reduce_state(self.state, intent)
        if intent.type in layout_intents:
            after_layout = self._layout_inputs()
            if after_layout == before_layout:
                return
            self._layout_pending = True
            if self._sticky_inputs() != before_sticky:
                save_sticky_state(self.state)

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
            get_computer_info=self._get_computer_info,
            active_doc_preview=layout.active_doc_preview,
            sticky_doc_previews=layout.sticky_doc_previews,
            focus=focus,
        )

    def apply_pending_layout(self) -> bool:
        """Apply deferred layout work once per loop tick."""
        if not self._layout_pending:
            return False
        self._layout_pending = False
        self.apply_layout(focus=False)
        return True

    def _derive_layout(self) -> LayoutState:
        preview = self.state.sessions.preview
        active_session_id = preview.session_id if preview else None
        sticky_session_ids = [s.session_id for s in self.state.sessions.sticky_sessions]
        active_doc_preview = self.state.preparation.preview
        sticky_doc_previews = list(self.state.preparation.sticky_previews)
        return LayoutState(
            active_session_id=active_session_id,
            sticky_session_ids=sticky_session_ids,
            active_doc_preview=active_doc_preview,
            sticky_doc_previews=sticky_doc_previews,
        )
