"""Bridge between Textual messages and TmuxPaneManager."""

from __future__ import annotations

import queue
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from textual.widget import Widget

from teleclaude.cli.tui.artifact_panes import doc_pane_key
from teleclaude.cli.tui.base import TelecMixin
from teleclaude.cli.tui.messages import (
    DocEditRequest,
    DocPreviewRequest,
    DocPreviewRestored,
    FocusPaneRequest,
    PreviewChanged,
    StickyChanged,
)
from teleclaude.cli.tui.pane_manager import TmuxPaneManager
from teleclaude.cli.tui.types import ArtifactPreviewIntent, DocPreviewState, PreviewIntent, SessionPreviewIntent

logger = get_logger(__name__)

if TYPE_CHECKING:
    from teleclaude.api_models import SessionDTO

PANE_WRITER_ERRORS = (
    AttributeError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    subprocess.SubprocessError,
)


@dataclass(frozen=True)
class _PaneOperation:
    run: Callable[[], None] | None
    coalesce: bool = False


class PaneWriter:
    """Serial writer thread for pane operations with latest-wins coalescing.

    All pane operations (layout, focus, reapply) are enqueued and executed
    by a single dedicated thread.  This guarantees:
    1. Serial execution — no concurrent PaneState mutation.
    2. Non-blocking — the Textual event loop never waits for tmux subprocesses.
    3. Complete layout snapshots coalesce; other operations preserve ordering.
    """

    def __init__(
        self,
        pane_manager: TmuxPaneManager,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._pm = pane_manager
        self._on_error = on_error
        self._queue: queue.Queue[_PaneOperation] = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="pane-writer")
        self._thread.start()

    def schedule(self, fn: Callable[[], None], *, coalesce: bool = False) -> None:
        """Enqueue an operation, optionally coalescing complete layout snapshots."""
        self._queue.put(_PaneOperation(fn, coalesce))

    def stop(self) -> None:
        """Signal the writer thread to exit and wait for it."""
        self._queue.put(_PaneOperation(None))
        self._thread.join(timeout=5)

    def _run(self) -> None:
        """Process pane operations serially, coalescing pending ones."""
        pending: _PaneOperation | None = None
        while True:
            item = pending if pending is not None else self._queue.get()
            pending = None
            if item.run is None:
                break

            # Drain: if more items arrived while we were blocked or executing
            # the previous operation, use only the latest.
            latest = item
            while latest.coalesce:
                try:
                    peek = self._queue.get_nowait()
                except queue.Empty:
                    break
                if not peek.coalesce:
                    pending = peek
                    break
                latest = peek

            self._execute(latest.run)

    @staticmethod
    def _execute(fn: object) -> None:
        if not callable(fn):
            return
        try:
            fn()
        except PANE_WRITER_ERRORS:
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
        self._is_reload = is_reload
        self.pane_manager: TmuxPaneManager | None = None
        self._writer: PaneWriter | None = None
        self._sessions: list[SessionDTO] = []
        self._preview_intent: PreviewIntent = None
        self._sticky_session_ids: list[str] = []
        self._layout_dirty: bool = False
        self._pending_focus: bool = False
        self._preview_revision = 0
        self._session_snapshot_ready = not is_reload

    def attach_tmux(self, tmux_binary: str) -> None:
        """Build the pane manager once the daemon has projected this computer's tmux binary.

        Layout requested before then stays dirty and is applied on attach.
        """
        if self.pane_manager is not None:
            return
        self.pane_manager = TmuxPaneManager(tmux_binary=tmux_binary, is_reload=self._is_reload)
        self._writer = PaneWriter(self.pane_manager)
        self._mark_layout_dirty()

    def _mark_layout_dirty(self, *, focus: bool = False) -> None:
        """Mark layout as needing recalculation.

        Multiple state changes within the same event loop iteration are
        batched — only a single layout application runs after all pending
        Textual messages settle.  Uses call_later which posts a one-shot
        CallbackMessage to this widget's pump queue, processed after the
        current message handlers return.
        """
        self._pending_focus = self._pending_focus or focus
        if not self._layout_dirty:
            self._layout_dirty = True
            self.call_later(self._flush_layout)

    def _flush_layout(self) -> None:
        """Apply the accumulated layout state after all pending messages settle."""
        if not self._layout_dirty:
            return
        self._layout_dirty = False
        focus = self._pending_focus
        self._pending_focus = False
        self._apply(focus=focus)

    def _apply(self, *, focus: bool = True) -> None:
        """Apply the current layout to the pane manager (non-blocking).

        Snapshots current state and enqueues a layout operation on the
        PaneWriter thread.  If multiple _apply calls fire before the
        writer processes one, only the latest snapshot is executed.
        """
        pane_manager = self.pane_manager
        writer = self._writer
        if pane_manager is None or writer is None or not self._session_snapshot_ready:
            return
        # Snapshot mutable state for the writer thread
        sessions = self._sessions
        preview_intent = self._preview_intent
        sticky_ids = list(self._sticky_session_ids)
        preview_revision = self._preview_revision

        def _do_layout() -> None:
            pane_manager.update_session_catalog(sessions)
            if pane_manager.has_reload_panes():
                pane_manager.seed_for_reload(
                    active_doc_preview=self._artifact_preview(preview_intent),
                    adopt_discovered_artifact=(
                        preview_revision == 0 and not isinstance(preview_intent, ArtifactPreviewIntent)
                    ),
                )
            restored_doc = pane_manager.adopted_doc_preview()
            effective_intent = preview_intent
            if (
                restored_doc is not None
                and preview_revision == 0
                and not isinstance(preview_intent, ArtifactPreviewIntent)
            ):
                effective_intent = ArtifactPreviewIntent(restored_doc)
                self.post_message(DocPreviewRestored(restored_doc, preview_revision))
            pane_manager.apply_layout(
                active_session_id=self._session_preview_id(effective_intent),
                sticky_session_ids=sticky_ids,
                active_doc_preview=self._artifact_preview(effective_intent),
                focus=False,
            )

        writer.schedule(_do_layout, coalesce=True)
        doc_preview = self._artifact_preview(preview_intent)
        focus_id = self._session_preview_id(preview_intent) or (
            doc_pane_key(doc_preview.doc_id) if doc_preview is not None else None
        )
        if focus and focus_id is not None:
            writer.schedule(lambda: pane_manager.focus_pane_for_session(focus_id))

    @staticmethod
    def _session_preview_id(intent: PreviewIntent) -> str | None:
        """Return the session id carried by a session preview intent."""
        return intent.session_id if isinstance(intent, SessionPreviewIntent) else None

    @staticmethod
    def _artifact_preview(intent: PreviewIntent) -> DocPreviewState | None:
        """Return the artifact carried by an artifact preview intent."""
        return intent.preview if isinstance(intent, ArtifactPreviewIntent) else None

    def update_single_session(self, session: SessionDTO) -> None:
        """Update or add a single session in the bridge's session list and catalog.

        Called from on_session_started/on_session_updated so the bridge has
        current session data before any PreviewChanged layout runs.
        """
        updated = False
        next_sessions: list[SessionDTO] = []
        for existing in self._sessions:
            if existing.session_id == session.session_id:
                next_sessions.append(session)
                updated = True
            else:
                next_sessions.append(existing)
        if not updated:
            next_sessions.append(session)
        self._sessions = next_sessions
        self._mark_layout_dirty()

    def remove_session(self, session_id: str) -> None:
        """Remove a session from the bridge's session list and catalog."""
        self._sessions = [s for s in self._sessions if s.session_id != session_id]
        self._mark_layout_dirty()

    def update_sessions(self, sessions: list[SessionDTO]) -> None:
        """Reconcile the complete session snapshot through the serial pane writer.

        Snapshot absence is not closure: a session still claimed as preview or
        sticky stays in the catalog, so its pane lives and dies by tmux liveness
        and the explicit closure that calls ``remove_session``.
        """
        self._session_snapshot_ready = True
        present = {session.session_id for session in sessions}
        claimed = {*self._sticky_session_ids, self._session_preview_id(self._preview_intent)}
        retained = [s for s in self._sessions if s.session_id in claimed and s.session_id not in present]
        self._sessions = [*sessions, *retained]
        self._mark_layout_dirty()

    def sync_layout_state(
        self,
        *,
        preview_intent: PreviewIntent,
        sticky_session_ids: list[str],
        preview_revision: int,
    ) -> None:
        """Mirror the Sessions-view intent and stickies without scheduling layout."""
        self._preview_intent = preview_intent
        self._sticky_session_ids = list(sticky_session_ids)
        self._preview_revision = preview_revision

    def apply_preview_intent(self, intent: PreviewIntent, *, focus: bool) -> None:
        """Apply a complete preview intent snapshot from its local owner."""
        self._preview_intent = intent
        self._mark_layout_dirty(focus=focus)

    def on_preview_changed(self, message: PreviewChanged) -> None:
        """Handle preview session change — update active pane."""
        if message.revision is not None:
            self._preview_revision = message.revision
        intent = SessionPreviewIntent(message.session_id) if message.session_id is not None else None
        self.apply_preview_intent(intent, focus=message.request_focus)

    def on_sticky_changed(self, message: StickyChanged) -> None:
        """Handle sticky sessions change — mark layout dirty without stealing focus."""
        self._sticky_session_ids = message.session_ids
        self._mark_layout_dirty(focus=False)

    def on_focus_pane_request(self, message: FocusPaneRequest) -> None:
        """Handle explicit focus request (non-blocking)."""
        session_id = message.session_id
        pane_manager = self.pane_manager
        if pane_manager is None or self._writer is None:
            return
        self._writer.schedule(lambda: pane_manager.focus_pane_for_session(session_id))

    def on_doc_preview_request(self, message: DocPreviewRequest) -> None:
        """Handle doc preview request — view mode without focus."""
        self.apply_preview_intent(
            ArtifactPreviewIntent(DocPreviewState(doc_id=message.doc_id, command=message.command, title=message.title)),
            focus=False,
        )

    def on_doc_edit_request(self, message: DocEditRequest) -> None:
        """Handle doc edit request — edit mode with focus."""
        self.apply_preview_intent(
            ArtifactPreviewIntent(DocPreviewState(doc_id=message.doc_id, command=message.command, title=message.title)),
            focus=True,
        )

    def reapply_colors(self) -> None:
        """Re-apply agent colors after theme change (non-blocking)."""
        if self.pane_manager is None or self._writer is None:
            return
        self._writer.schedule(self.pane_manager.reapply_agent_colors)

    def cleanup(self) -> None:
        """Clean up all panes on exit."""
        if self.pane_manager is None or self._writer is None:
            return
        self._writer.stop()
        self.pane_manager.cleanup()
