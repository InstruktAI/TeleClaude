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
from teleclaude.cli.tui.state import DocPreviewState, Intent, IntentType, TuiState, reduce_state
from teleclaude.cli.tui.state_store import save_sticky_state

logger = get_logger(__name__)


@dataclass(frozen=True)
class LayoutState:
    """Derived pane layout inputs."""

    active_session_id: str | None
    sticky_session_ids: list[str]
    active_doc_preview: DocPreviewState | None
    selected_session_id: str | None
    tree_node_has_focus: bool


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
        self._pending_focus_session_id: str | None = None

    def update_sessions(self, sessions: list[SessionInfo]) -> None:
        """Update session catalog used for layout derivation."""
        self._sessions = sessions

    def _layout_inputs(self) -> tuple[object, ...]:
        preview = self.state.sessions.preview
        preview_key = preview.session_id if preview else None
        sticky_key = tuple(s.session_id for s in self.state.sessions.sticky_sessions)
        prep_preview = self.state.preparation.preview
        prep_preview_key = (prep_preview.doc_id, prep_preview.command, prep_preview.title) if prep_preview else None
        return (preview_key, sticky_key, prep_preview_key)

    def _sticky_inputs(self) -> tuple[object, ...]:
        sticky_key = tuple(s.session_id for s in self.state.sessions.sticky_sessions)
        return (sticky_key,)

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

        if intent.type is IntentType.SET_PREVIEW:
            focus_requested = bool(intent.payload.get("focus_preview", False))
            target_session = intent.payload.get("session_id")
            if focus_requested and isinstance(target_session, str):
                self._pending_focus_session_id = target_session
            elif not focus_requested:
                self._pending_focus_session_id = None
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
        should_focus = focus or self._pending_focus_session_id is not None
        layout_changed = self._last_layout != layout

        if not layout_changed and not should_focus:
            return

        # Only call the (expensive) pane_manager.apply_layout when the
        # structural layout actually changed.  Focus-only transitions skip
        # the full apply and go straight to focus_pane_for_session.
        if layout_changed:
            self._last_layout = layout
            self.pane_manager.apply_layout(
                active_session_id=layout.active_session_id,
                sticky_session_ids=layout.sticky_session_ids,
                get_computer_info=self._get_computer_info,
                active_doc_preview=layout.active_doc_preview,
                selected_session_id=layout.selected_session_id,
                tree_node_has_focus=layout.tree_node_has_focus,
                focus=False,
            )

        if should_focus:
            focus_session_id = self._pending_focus_session_id or layout.active_session_id
            if not focus_session_id and layout.active_doc_preview:
                focus_session_id = f"doc:{layout.active_doc_preview.doc_id}"
            if focus_session_id:
                self.pane_manager.focus_pane_for_session(focus_session_id)

    def has_pending_focus(self) -> bool:
        """Whether a focus transition has been requested by the latest intent."""
        return self._pending_focus_session_id is not None

    def request_focus_session(self, session_id: str | None) -> None:
        """Request that the next layout application focuses the given session."""
        if session_id is None:
            self._pending_focus_session_id = None
            return
        self._pending_focus_session_id = session_id

    def apply_pending_layout(self) -> bool:
        """Apply deferred layout work once per loop tick."""
        pending_focus = self._pending_focus_session_id is not None
        if not self._layout_pending and not pending_focus:
            return False
        self._layout_pending = False
        self.apply_layout(focus=pending_focus)
        self._pending_focus_session_id = None
        return True

    def _derive_layout(self) -> LayoutState:
        preview = self.state.sessions.preview
        active_session_id = preview.session_id if preview else None
        sticky_session_ids = [s.session_id for s in self.state.sessions.sticky_sessions]
        active_doc_preview = self.state.preparation.preview
        selection_method = self.state.sessions.selection_method
        tree_node_has_focus = selection_method in ("arrow", "click")
        return LayoutState(
            active_session_id=active_session_id,
            sticky_session_ids=sticky_session_ids,
            active_doc_preview=active_doc_preview,
            selected_session_id=self.state.sessions.selected_session_id,
            tree_node_has_focus=tree_node_has_focus,
        )
