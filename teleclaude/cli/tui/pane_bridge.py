"""Bridge between Textual messages and TmuxPaneManager."""

from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING, Callable

from instrukt_ai_logging import get_logger
from textual.widget import Widget

from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.messages import (
    DataRefreshed,
    DocEditRequest,
    DocPreviewRequest,
    FocusPaneRequest,
    PreviewChanged,
    StickyChanged,
)
from teleclaude.cli.tui.pane_manager import ComputerInfo, TmuxPaneManager
from teleclaude.cli.tui.state import DocPreviewState

logger = get_logger(__name__)

if TYPE_CHECKING:
    from teleclaude.cli.models import ComputerInfo as APIComputerInfo
    from teleclaude.cli.models import SessionInfo

_SENTINEL = object()


class PaneWriter:
    """Serial writer thread for pane operations with latest-wins coalescing.

    All pane operations (layout, focus, reapply) are enqueued and executed
    by a single dedicated thread.  This guarantees:
    1. Serial execution — no concurrent PaneState mutation.
    2. Non-blocking — the Textual event loop never waits for tmux subprocesses.
    3. Coalescing — if multiple requests pile up while one executes, only the
       latest is processed.  Intermediate states are skipped.
    """

    def __init__(self, pane_manager: TmuxPaneManager) -> None:
        self._pm = pane_manager
        self._queue: queue.Queue[Callable[[], None] | object] = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="pane-writer")
        self._thread.start()

    def schedule(self, fn: Callable[[], None]) -> None:
        """Enqueue a pane operation.  Latest-wins coalescing applied."""
        self._queue.put(fn)

    def stop(self) -> None:
        """Signal the writer thread to exit and wait for it."""
        self._queue.put(_SENTINEL)
        self._thread.join(timeout=5)

    def _run(self) -> None:
        """Process pane operations serially, coalescing pending ones."""
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                break

            # Drain: if more items arrived while we were blocked or executing
            # the previous operation, use only the latest.
            latest = item
            while not self._queue.empty():
                try:
                    peek = self._queue.get_nowait()
                except queue.Empty:
                    break
                if peek is _SENTINEL:
                    # Execute the current latest, then exit.
                    self._execute(latest)
                    return
                latest = peek

            self._execute(latest)

    @staticmethod
    def _execute(fn: object) -> None:
        if not callable(fn):
            return
        try:
            fn()
        except Exception:
            logger.exception("PaneWriter error")


class PaneManagerBridge(TelecMixin, Widget):
    """Invisible widget that bridges Textual messages to TmuxPaneManager.

    Listens for PreviewChanged, StickyChanged, and FocusPaneRequest messages
    and translates them into pane_manager.apply_layout() calls.
    No polling. Events only.

    All blocking tmux work is dispatched to a single PaneWriter thread
    to keep the Textual event loop free while guaranteeing serial access
    to PaneState.
    """

    DEFAULT_CSS = """
    PaneManagerBridge {
        display: none;
    }
    """

    def __init__(self, *, is_reload: bool = False, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.pane_manager = TmuxPaneManager(is_reload=is_reload)
        self._writer = PaneWriter(self.pane_manager)
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

        Snapshots current state and enqueues a layout operation on the
        PaneWriter thread.  If multiple _apply calls fire before the
        writer processes one, only the latest snapshot is executed.
        """
        # Snapshot mutable state for the writer thread
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

        self._writer.schedule(_do_layout)

    def upsert_session(self, session: "SessionInfo") -> None:
        """Update one session in the cached catalog and refresh pane colors if needed."""
        if not session.session_id:
            return

        current_agent = session.active_agent
        needs_recompute = True

        for i, existing in enumerate(self._sessions):
            if existing.session_id != session.session_id:
                continue
            needs_recompute = (
                existing.active_agent != current_agent
                or existing.tmux_session_name != session.tmux_session_name
                or existing.computer != session.computer
            )
            self._sessions[i] = session
            break
        else:
            self._sessions.append(session)

        if needs_recompute:
            self._apply(focus=False)

    def on_data_refreshed(self, message: DataRefreshed) -> None:
        """Update cached data from API refresh."""
        self._computers = {c.name: c for c in message.computers}
        self._sessions = message.sessions
        self.pane_manager.update_session_catalog(self._sessions)

        # On reload, map discovered panes to session state now that the
        # session catalog is available.  This replaces seed_layout_for_reload.
        if self.pane_manager._reload_session_panes:
            self.pane_manager.seed_for_reload(
                active_session_id=self._preview_session_id,
                sticky_session_ids=list(self._sticky_session_ids),
                get_computer_info=self._get_computer_info,
            )

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
        self._writer.schedule(lambda: self.pane_manager.focus_pane_for_session(session_id))

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

    def on_doc_edit_request(self, message: DocEditRequest) -> None:
        """Handle doc edit request — same as preview but with editor command."""
        logger.debug("on_doc_edit_request: doc=%s", message.doc_id)
        self._preview_session_id = None
        self._active_doc_preview = DocPreviewState(
            doc_id=message.doc_id,
            command=message.command,
            title=message.title,
        )
        self._apply()

    def reapply_colors(self) -> None:
        """Re-apply agent colors after theme change (non-blocking)."""
        self._writer.schedule(self.pane_manager.reapply_agent_colors)

    def cleanup(self) -> None:
        """Clean up all panes on exit."""
        self._writer.stop()
        self.pane_manager.cleanup()
