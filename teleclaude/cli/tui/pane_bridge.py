"""Bridge between Textual messages and TmuxPaneManager."""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.messages import (
    DataRefreshed,
    DocPreviewRequest,
    FocusPaneRequest,
    PreviewChanged,
    StickyChanged,
)
from teleclaude.cli.tui.pane_manager import ComputerInfo, SessionPaneSpec, TmuxPaneManager
from teleclaude.cli.tui.state import DocPreviewState

logger = get_logger(__name__)

if TYPE_CHECKING:
    from teleclaude.cli.models import ComputerInfo as APIComputerInfo
    from teleclaude.cli.models import SessionInfo


class PaneManagerBridge(TelecMixin, Widget):
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
        self._active_doc_preview: DocPreviewState | None = None

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
        """Apply the current layout to the pane manager (non-blocking).

        Runs blocking tmux subprocess calls in a background thread so
        Textual's event loop stays responsive for rendering.
        """
        # Snapshot mutable state for thread safety
        sessions = self._sessions
        preview_id = self._preview_session_id
        sticky_ids = list(self._sticky_session_ids)
        doc_preview = self._active_doc_preview

        def _do_layout() -> None:
            self.pane_manager.update_session_catalog(sessions)
            self.pane_manager.apply_layout(
                active_session_id=preview_id,
                sticky_session_ids=sticky_ids,
                get_computer_info=self._get_computer_info,
                active_doc_preview=doc_preview,
                focus=focus,
            )

        self.run_worker(_do_layout, exclusive=True, group="pane-layout", thread=True)

    def on_data_refreshed(self, message: DataRefreshed) -> None:
        """Update cached data from API refresh."""
        self._computers = {c.name: c for c in message.computers}
        self._sessions = message.sessions
        self.pane_manager.update_session_catalog(self._sessions)

    def on_preview_changed(self, message: PreviewChanged) -> None:
        """Handle preview session change — update active pane."""
        logger.debug(
            "on_preview_changed: session=%s focus=%s (was=%s)",
            message.session_id[:8] if message.session_id else None,
            message.request_focus,
            self._preview_session_id[:8] if self._preview_session_id else None,
        )
        self._preview_session_id = message.session_id
        if message.session_id:
            self._active_doc_preview = None  # Session and doc preview are mutually exclusive
        self._apply(focus=message.request_focus)

    def on_sticky_changed(self, message: StickyChanged) -> None:
        """Handle sticky sessions change — rebuild layout without stealing focus."""
        logger.debug(
            "on_sticky_changed: ids=%s (was=%s)",
            [s[:8] for s in message.session_ids],
            [s[:8] for s in self._sticky_session_ids],
        )
        self._sticky_session_ids = message.session_ids
        self._apply(focus=False)

    def on_focus_pane_request(self, message: FocusPaneRequest) -> None:
        """Handle explicit focus request (non-blocking)."""
        session_id = message.session_id

        def _do_focus() -> None:
            self.pane_manager.focus_pane_for_session(session_id)

        self.run_worker(_do_focus, thread=True, group="pane-focus")

    def on_doc_preview_request(self, message: DocPreviewRequest) -> None:
        """Handle doc preview request from preparation view."""
        logger.debug(
            "on_doc_preview_request: doc=%s (clearing preview=%s)",
            message.doc_id,
            self._preview_session_id[:8] if self._preview_session_id else None,
        )
        self._preview_session_id = None
        self._active_doc_preview = DocPreviewState(
            doc_id=message.doc_id,
            command=message.command,
            title=message.title,
        )
        self._apply()

    def seed_layout_for_reload(
        self,
        *,
        active_session_id: str | None,
        sticky_session_ids: list[str],
        get_computer_info: object,
    ) -> None:
        """Pre-compute pane manager specs and layout signature for reload.

        Called on SIGUSR2 reload to make the pane manager aware of the
        current layout WITHOUT calling apply_layout (which would tear down
        and recreate all panes). The first user interaction after reload
        will then take the lightweight _update_active_pane path.
        """
        pm = self.pane_manager
        pm.update_session_catalog(self._sessions)

        # Build sticky specs (same logic as apply_layout)
        sticky_specs = []
        for session_id in sticky_session_ids:
            session = pm._session_catalog.get(session_id)
            if not session or not session.tmux_session_name:
                continue
            sticky_specs.append(
                PaneManagerBridge._make_spec(session, is_sticky=True, get_computer_info=self._get_computer_info)
            )
        pm._sticky_specs = sticky_specs

        # Build active spec and map parent pane to active session
        if active_session_id:
            session = pm._session_catalog.get(active_session_id)
            if session and session.tmux_session_name:
                pm._active_spec = PaneManagerBridge._make_spec(
                    session, is_sticky=False, get_computer_info=self._get_computer_info
                )
                pm.state.parent_session = session.tmux_session_name
                pm.state.parent_spec_id = session.session_id
                if pm.state.parent_pane_id:
                    pm.state.session_to_pane[session.session_id] = pm.state.parent_pane_id

        # Compute and set the layout signature so _layout_is_unchanged()
        # returns True on the next apply_layout call.
        pm._layout_signature = pm._compute_layout_signature()

    @staticmethod
    def _make_spec(
        session: SessionInfo,
        *,
        is_sticky: bool,
        get_computer_info: object,
    ) -> SessionPaneSpec:
        """Build a SessionPaneSpec from a SessionInfo."""
        computer_info = get_computer_info(session.computer or "local") if callable(get_computer_info) else None
        return SessionPaneSpec(
            session_id=session.session_id,
            tmux_session_name=session.tmux_session_name or "",
            computer_info=computer_info,
            is_sticky=is_sticky,
            active_agent=session.active_agent,
        )

    def reapply_colors(self) -> None:
        """Re-apply agent colors after theme change (non-blocking)."""

        def _do_reapply() -> None:
            self.pane_manager.reapply_agent_colors()

        self.run_worker(_do_reapply, thread=True, group="pane-colors")

    def cleanup(self) -> None:
        """Clean up all panes on exit."""
        self.pane_manager.cleanup()
