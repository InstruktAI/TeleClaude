"""Sessions view with hierarchical tree display."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger as _get_logger
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.models import ComputerInfo, ProjectInfo, SessionInfo
from teleclaude.cli.tui.messages import (
    PreviewChanged,
    ReviveSessionRequest,
    StateChanged,
    StickyChanged,
)
from teleclaude.cli.tui.tree import (
    ComputerDisplayInfo,
    SessionDisplayInfo,
    build_tree,
    is_computer_node,
    is_project_node,
    is_session_node,
)
from teleclaude.cli.tui.views.interaction import TreeInteractionState
from teleclaude.cli.tui.views.sessions_actions import (
    DOUBLE_PRESS_THRESHOLD,
    SessionsViewActionsMixin,
)
from teleclaude.cli.tui.views.sessions_highlights import (
    HIDDEN_SESSION_STATUSES,
    PREVIEW_HIGHLIGHT_DURATION,
    SessionsViewHighlightsMixin,
)
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.group_separator import GroupSeparator
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.session_row import SessionRow

if TYPE_CHECKING:
    from teleclaude.cli.models import AgentAvailabilityInfo
    from teleclaude.cli.tui.tree import TreeNode


class SessionsView(SessionsViewActionsMixin, SessionsViewHighlightsMixin, Widget, can_focus=True):
    """Sessions tab view with hierarchical tree and keyboard navigation.

    Handles: arrow nav, Space (preview/sticky), Enter (focus pane),
    Left/Right (collapse/expand), +/- (expand/collapse all),
    n (new session), k (kill session), a (toggle project sessions sticky).
    """

    DEFAULT_CSS = """
    SessionsView {
        width: 100%;
        height: 1fr;
    }
    SessionsView VerticalScroll {
        width: 100%;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up", key_display="↑", group=Binding.Group("Nav", compact=True), show=False),
        Binding("down", "cursor_down", "Down", key_display="↓", group=Binding.Group("Nav", compact=True), show=False),
        Binding("space", "toggle_preview", "Preview/Sticky"),
        Binding("enter", "focus_pane", "Focus"),
        Binding("left", "collapse", "Collapse", key_display="←", group=Binding.Group("Fold", compact=True), show=False),
        Binding("right", "expand", "Expand", key_display="→", group=Binding.Group("Fold", compact=True), show=False),
        Binding("equals_sign", "expand_all", "All", key_display="+", group=Binding.Group("Fold", compact=True)),
        Binding("minus", "collapse_all", "None", key_display="-", group=Binding.Group("Fold", compact=True)),
        Binding("n", "new_session", "New"),
        Binding("n", "new_project", "New Project"),
        Binding("k", "kill_session", "Kill"),
        Binding("R", "restart_session", "Restart"),
        Binding("R", "restart_project", "Restart All"),
        Binding("R", "restart_all", "Restart All"),
    ]

    preview_session_id = reactive[str | None](None)
    cursor_index = reactive(0)
    persistence_key = "sessions"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._computers: list[ComputerInfo] = []
        self._projects: list[ProjectInfo] = []
        self._sessions: list[SessionInfo] = []
        self._availability: dict[str, AgentAvailabilityInfo] = {}
        self._sticky_session_ids: list[str] = []
        self._input_highlights: set[str] = set()
        self._output_highlights: set[str] = set()
        # session_id → {"text": str, "ts": float (monotonic)}
        self._last_output_summary: dict[str, dict[str, object]] = {}  # guard: loose-dict
        self._collapsed_sessions: set[str] = set()
        self._optimistically_hidden_session_ids: set[str] = set()
        # TreeInteractionState for Space double-press detection
        self._interaction = TreeInteractionState()
        # Double-click detection for mouse clicks (separate from Space)
        self._last_click_time: float = 0.0
        self._last_click_session: str | None = None
        # Flat list of navigable widgets for keyboard nav
        self._nav_items: list[Widget] = []
        # Timers for auto-clearing highlights on preview sessions
        from textual.timer import Timer

        self._highlight_timers: dict[str, Timer] = {}
        # Track sessions already mounted this process — headless sessions
        # auto-expand only on first mount, not on tree rebuilds
        self._ever_mounted_sessions: set[str] = set()
        # Pending auto-select: session_id to select+preview once it appears
        # in the tree with a tmux pane ready
        self._pending_select_session_id: str | None = None
        # Position cursor at preview session on first tree build only
        self._initial_cursor_positioned = False
        # Track highlighted session by identity so cursor survives tree rebuilds
        self._highlighted_session_id: str | None = None

    def compose(self) -> ComposeResult:
        scroll = VerticalScroll(id="sessions-scroll")
        scroll.can_focus = False
        yield scroll

    _logger = _get_logger(__name__)

    def update_data(
        self,
        computers: list[ComputerInfo],
        projects: list[ProjectInfo],
        sessions: list[SessionInfo],
        availability: dict[str, AgentAvailabilityInfo] | None = None,
    ) -> None:
        """Update view with fresh API data. Only rebuild tree if structure changed."""
        self._logger.trace("[PERF] SessionsView.update_data called sessions=%d t=%.3f", len(sessions), time.monotonic())
        restored_hidden = {
            session.session_id
            for session in sessions
            if session.session_id in self._optimistically_hidden_session_ids and session.status not in HIDDEN_SESSION_STATUSES
        }
        if restored_hidden:
            self._optimistically_hidden_session_ids.difference_update(restored_hidden)

        visible_sessions = [
            session for session in sessions if session.session_id not in self._optimistically_hidden_session_ids
        ]
        old_ids = {s.session_id for s in self._sessions}
        new_ids = {s.session_id for s in visible_sessions}
        self._computers = computers
        self._projects = projects
        self._sessions = visible_sessions
        if availability is not None:
            self._availability = availability

        # Prune stale session IDs from sticky/preview state
        state_changed = bool(restored_hidden)
        stale_sticky = [sid for sid in self._sticky_session_ids if sid not in new_ids]
        if stale_sticky:
            self._logger.info("Pruning %d stale sticky IDs: %s", len(stale_sticky), stale_sticky)
            self._sticky_session_ids = [sid for sid in self._sticky_session_ids if sid in new_ids]
            state_changed = True
            # Notify bridge so panes for dead sessions are actually removed.
            self.post_message(StickyChanged(self._sticky_session_ids.copy()))
        if self.preview_session_id and self.preview_session_id not in new_ids:
            self._logger.info("Pruning stale preview ID: %s", self.preview_session_id)
            self.preview_session_id = None
            state_changed = True
            self.post_message(PreviewChanged(None, request_focus=False))
        stale_summaries = self._last_output_summary.keys() - new_ids
        if stale_summaries:
            for sid in stale_summaries:
                del self._last_output_summary[sid]

        if old_ids != new_ids or not self._nav_items:
            # Session list changed — full rebuild (includes _apply_pending_selection)
            self._rebuild_tree()
        else:
            # Same sessions — just update data on existing rows
            session_map = {s.session_id: s for s in visible_sessions}
            for widget in self._nav_items:
                if isinstance(widget, SessionRow) and widget.session_id in session_map:
                    widget.update_session(session_map[widget.session_id])
            # Session data updated — pending session may now have a tmux pane
            self._apply_pending_selection()

        if state_changed:
            self._notify_state_changed()

    def load_persisted_state(self, data: dict[str, object]) -> None:  # guard: loose-dict
        """Restore persisted state from state_store."""
        sticky_data = data.get("sticky_sessions", [])
        if isinstance(sticky_data, list):
            self._sticky_session_ids = [
                str(item.get("session_id", ""))
                for item in sticky_data
                if isinstance(item, dict) and item.get("session_id")
            ]

        input_highlights = data.get("input_highlights", [])
        if isinstance(input_highlights, list):
            self._input_highlights = {str(item) for item in input_highlights}

        output_highlights = data.get("output_highlights", [])
        if isinstance(output_highlights, list):
            self._output_highlights = {str(item) for item in output_highlights}

        last_output_summary = data.get("last_output_summary", {})
        if isinstance(last_output_summary, dict):
            parsed: dict[str, dict[str, object]] = {}  # guard: loose-dict - persisted activity summaries
            for session_id, value in last_output_summary.items():
                if not isinstance(session_id, str):
                    continue
                if isinstance(value, dict) and "text" in value:
                    parsed[session_id] = value
                elif isinstance(value, str):
                    parsed[session_id] = {"text": value, "ts": 0.0}
            self._last_output_summary = parsed

        collapsed_sessions = data.get("collapsed_sessions", [])
        if isinstance(collapsed_sessions, list):
            self._collapsed_sessions = {str(item) for item in collapsed_sessions}

        preview_data = data.get("preview")
        if isinstance(preview_data, dict):
            preview_id = preview_data.get("session_id")
            if isinstance(preview_id, str) and preview_id:
                self.preview_session_id = preview_id

        highlighted = data.get("highlighted_session_id")
        if isinstance(highlighted, str) and highlighted:
            self._highlighted_session_id = highlighted

    def request_select_session(self, session_id: str) -> None:
        """Request auto-selection of a session once it appears in the tree.

        Called when a new session is created — the session may not yet be in
        the tree or may not yet have a tmux pane. The pending ID is applied
        after the next tree rebuild.
        """
        self._pending_select_session_id = session_id

    def _apply_pending_selection(self) -> None:
        """Apply pending auto-select if the session is in the tree and ready.

        A session is "ready" when it has a tmux_session_name (pane exists).
        If not ready yet, the pending ID is kept for the next data update.
        """
        if not self._pending_select_session_id:
            return

        target_id = self._pending_select_session_id
        for i, widget in enumerate(self._nav_items):
            if isinstance(widget, SessionRow) and widget.session_id == target_id:
                # Found in tree — check if it has a tmux pane
                if not widget.session.tmux_session_name:
                    # Not ready yet — keep pending for next update
                    return
                # Ready — select, preview, and focus
                self._pending_select_session_id = None
                self.cursor_index = i
                self._update_cursor_highlight()
                self._scroll_to_cursor()
                self.preview_session_id = target_id
                self._clear_session_highlights(target_id)
                self.post_message(PreviewChanged(target_id, request_focus=False))
                self._notify_state_changed()
                return

        # Not in tree yet — keep pending

    def _rebuild_tree(self) -> None:
        """Rebuild the tree display from current data."""
        _rt0 = time.monotonic()
        self._logger.trace("[PERF] SessionsView._rebuild_tree START t=%.3f", _rt0)

        # Capture cursor identity before clearing the tree
        old_cursor_index = self.cursor_index
        old_highlighted_id = self._highlighted_session_id
        if not old_highlighted_id and self._nav_items and 0 <= old_cursor_index < len(self._nav_items):
            item = self._nav_items[old_cursor_index]
            if isinstance(item, SessionRow):
                old_highlighted_id = item.session_id

        container = self.query_one("#sessions-scroll", VerticalScroll)
        container.remove_children()
        self._nav_items.clear()

        # Build computer display info
        session_counts: dict[str, int] = {}
        for s in self._sessions:
            comp = s.computer or "local"
            session_counts[comp] = session_counts.get(comp, 0) + 1

        computer_display = [
            ComputerDisplayInfo(
                computer=c,
                session_count=session_counts.get(c.name, 0),
                recent_activity=False,
            )
            for c in self._computers
        ]

        # Sort sessions by creation time for stable tree positions (the API
        # returns them sorted by last_activity which causes sessions to jump).
        sorted_sessions = sorted(self._sessions, key=lambda s: s.created_at or "", reverse=True)
        tree = build_tree(computer_display, self._projects, sorted_sessions)

        for node in tree:
            self._mount_node(container, node)

        # Mark last-child sessions: a session uses └ when the next session
        # in the flat list is at a shallower depth (subtree closing).
        session_rows = [w for w in self._nav_items if isinstance(w, SessionRow)]
        for i, row in enumerate(session_rows):
            if i + 1 < len(session_rows):
                row.is_last_child = session_rows[i + 1].depth < row.depth
            # Last session in group is handled by skip_bottom_connector

        # Restore cursor to the same session by identity
        restored = False
        if old_highlighted_id and self._nav_items:
            for i, widget in enumerate(self._nav_items):
                if isinstance(widget, SessionRow) and widget.session_id == old_highlighted_id:
                    self.cursor_index = i
                    self._highlighted_session_id = old_highlighted_id
                    restored = True
                    break

        if not restored and self._nav_items:
            # Session was removed — clamp to nearest valid position
            self.cursor_index = min(old_cursor_index, len(self._nav_items) - 1)
            item = self._nav_items[self.cursor_index]
            self._highlighted_session_id = item.session_id if isinstance(item, SessionRow) else None

        # On first build, position cursor at the preview session row
        if not self._initial_cursor_positioned and self.preview_session_id:
            for i, widget in enumerate(self._nav_items):
                if isinstance(widget, SessionRow) and widget.session_id == self.preview_session_id:
                    self.cursor_index = i
                    self._highlighted_session_id = self.preview_session_id
                    break
            self._initial_cursor_positioned = True

        self._update_cursor_highlight()
        self._logger.trace(
            "[PERF] SessionsView._rebuild_tree done items=%d dt=%.3f", len(self._nav_items), time.monotonic() - _rt0
        )

        # Apply pending auto-select after tree rebuild
        self._apply_pending_selection()

    def _mount_node(self, container: VerticalScroll, node: TreeNode) -> None:
        """Recursively mount tree nodes as widgets."""
        if is_computer_node(node):
            widget = ComputerHeader(data=node.data)
            container.mount(widget)
            self._nav_items.append(widget)
            for child in node.children:
                self._mount_node(container, child)

        elif is_project_node(node):
            session_count = len([c for c in node.children if is_session_node(c)])
            widget = ProjectHeader(project=node.data, session_count=session_count)
            container.mount(widget)
            self._nav_items.append(widget)
            for child in node.children:
                self._mount_node(container, child)
            # Closing separator after the last session in the group.
            # The last SessionRow skips its own bottom connector (└---) to
            # avoid a double line with the GroupSeparator.
            if session_count > 0:
                last_session_row = self._find_last_session_row_in_group(node)
                if last_session_row:
                    last_session_row.skip_bottom_connector = True
                    connector_col = last_session_row._connector_col
                else:
                    connector_col = 2
                container.mount(GroupSeparator(connector_col=connector_col))

        elif is_session_node(node):
            session_data: SessionDisplayInfo = node.data
            session = session_data.session
            row = SessionRow(
                session=session,
                display_index=session_data.display_index,
                depth=node.depth,
            )
            # Headless sessions auto-expand on first mount
            is_headless = (session.status or "").startswith("headless") or not session.tmux_session_name
            if is_headless and session.session_id not in self._ever_mounted_sessions:
                self._collapsed_sessions.add(session.session_id)
            self._ever_mounted_sessions.add(session.session_id)

            # Apply persisted/reactive state
            row.collapsed = session.session_id not in self._collapsed_sessions
            row.is_sticky = session.session_id in self._sticky_session_ids
            row.is_preview = session.session_id == self.preview_session_id

            # Apply highlights
            if session.session_id in self._input_highlights:
                row.highlight_type = "input"
            elif session.session_id in self._output_highlights:
                row.highlight_type = "output"

            # Restore persisted output text (WS-driven, survives reloads)
            stored = self._last_output_summary.get(session.session_id)
            if stored and stored.get("text"):
                row.last_output_summary = str(stored["text"])

            container.mount(row)
            self._nav_items.append(row)

            # Recurse into AI-to-AI children
            for child in node.children:
                self._mount_node(container, child)

    def _update_cursor_highlight(self) -> None:
        """Update the selected class on the current nav item and force re-render.

        Selection visuals are handled in each widget's render() method (not CSS),
        so we must explicitly refresh widgets when their selected state changes.
        """
        for i, widget in enumerate(self._nav_items):
            was_selected = widget.has_class("selected")
            is_selected = i == self.cursor_index
            widget.set_class(is_selected, "selected")
            if was_selected != is_selected:
                widget.refresh()

    def _current_session_row(self) -> SessionRow | None:
        """Get the SessionRow at the current cursor position, if any."""
        if not self._nav_items or self.cursor_index >= len(self._nav_items):
            return None
        item = self._nav_items[self.cursor_index]
        return item if isinstance(item, SessionRow) else None

    def _current_item(self) -> Widget | None:
        """Get current cursor item."""
        if not self._nav_items or self.cursor_index >= len(self._nav_items):
            return None
        return self._nav_items[self.cursor_index]

    def _notify_state_changed(self) -> None:
        self.post_message(StateChanged())
        self.refresh_bindings()

    # --- Helpers ---

    def _find_last_session_row_in_group(self, project_node: TreeNode) -> SessionRow | None:
        """Find the last SessionRow mounted for a project node.

        Walks the node's children (and their children for AI-to-AI nesting)
        in reverse to find the last session row that was just mounted.
        """

        def _find_last(children: list[TreeNode]) -> SessionRow | None:
            for child in reversed(children):
                if is_session_node(child):
                    # Check grandchildren first (AI-to-AI children)
                    if child.children:
                        result = _find_last(child.children)
                        if result:
                            return result
                    # This session node — find its row in nav_items
                    sid = child.data.session.session_id
                    for widget in reversed(self._nav_items):
                        if isinstance(widget, SessionRow) and widget.session_id == sid:
                            return widget
            return None

        return _find_last(project_node.children)

    def _find_nav_index(self, target: Widget) -> int:
        """Find the index of a widget in _nav_items by identity."""
        for i, widget in enumerate(self._nav_items):
            if widget is target:
                return i
        return -1

    def _is_headless(self, row: SessionRow) -> bool:
        """Check if a session row is headless (no tmux pane)."""
        status = row.status
        return status.startswith("headless") or not row.session.tmux_session_name

    def _revive_headless(self, row: SessionRow) -> None:
        """Request revive for a headless session."""
        self.post_message(
            ReviveSessionRequest(
                session_id=row.session_id,
                computer=row.session.computer or "local",
            )
        )

    def _clear_session_highlights(self, session_id: str) -> None:
        """Clear input/output visual highlights for a session.

        Only clears the visual emphasis (highlight_type). Activity state
        (activity_event/activity_text) is live in-memory state that persists
        until the next event replaces it — never cleared by UI interaction.
        """
        had_input = session_id in self._input_highlights
        had_output = session_id in self._output_highlights
        self._cancel_highlight_timer(session_id)
        self._input_highlights.discard(session_id)
        self._output_highlights.discard(session_id)
        changed = had_input or had_output
        for widget in self._nav_items:
            if isinstance(widget, SessionRow) and widget.session_id == session_id:
                widget.highlight_type = ""
                break
        if changed:
            self._notify_state_changed()

    def _cancel_highlight_timer(self, session_id: str) -> None:
        """Cancel any pending highlight auto-clear timer for a session."""
        timer = self._highlight_timers.pop(session_id, None)
        if timer is not None:
            timer.stop()

    def _schedule_highlight_clear(self, session_id: str) -> None:
        """Schedule auto-clear of highlights for preview session after timeout."""
        self._cancel_highlight_timer(session_id)
        self._highlight_timers[session_id] = self.set_timer(
            PREVIEW_HIGHLIGHT_DURATION,
            lambda sid=session_id: self._auto_clear_highlight(sid),
        )

    def _auto_clear_highlight(self, session_id: str) -> None:
        """Auto-clear callback — remove visual highlights only.

        Activity state (activity_event/activity_text) is in-memory state
        that leads over disk. It persists until the next event replaces it.
        """
        self._highlight_timers.pop(session_id, None)
        had_input = session_id in self._input_highlights
        had_output = session_id in self._output_highlights
        self._input_highlights.discard(session_id)
        self._output_highlights.discard(session_id)
        changed = had_input or had_output
        for widget in self._nav_items:
            if isinstance(widget, SessionRow) and widget.session_id == session_id:
                widget.highlight_type = ""
                break
        if changed:
            self._notify_state_changed()

    # --- Mouse click handling (widget-level Pressed messages) ---

    def on_session_row_pressed(self, message: SessionRow.Pressed) -> None:
        """Handle click on a session row.

        Single click: move cursor + preview with focus.
        Double click: toggle sticky.
        Shift+click: behave like Space (preview/sticky without focus).
        """
        row = message.session_row
        idx = self._find_nav_index(row)
        if idx < 0:
            return

        self.cursor_index = idx
        self._update_cursor_highlight()
        self._scroll_to_cursor()

        if message.shift:
            self.action_toggle_preview()
            self.focus()
            return

        session_id = row.session_id
        now = time.monotonic()

        # Double-click detection
        if self._last_click_session == session_id and (now - self._last_click_time) < DOUBLE_PRESS_THRESHOLD:
            was_sticky = session_id in self._sticky_session_ids
            self._toggle_sticky(session_id)
            if was_sticky:
                # Preserve pane-slot stability: removed sticky immediately becomes preview.
                self.preview_session_id = session_id
                self.post_message(PreviewChanged(session_id, request_focus=False))
                self._notify_state_changed()
            self._last_click_time = 0.0
            self._last_click_session = None
            return

        self._last_click_time = now
        self._last_click_session = session_id

        # Headless: revive instead of preview
        if self._is_headless(row):
            self._revive_headless(row)
            self.focus()
            return

        # Single click: preview with focus
        self.preview_session_id = session_id
        self._clear_session_highlights(session_id)
        self.post_message(PreviewChanged(session_id, request_focus=True))
        self._notify_state_changed()
        self.focus()

    def on_computer_header_pressed(self, message: ComputerHeader.Pressed) -> None:
        """Handle click on a computer header — cursor move only."""
        idx = self._find_nav_index(message.header)
        if idx >= 0:
            self.cursor_index = idx
            self._update_cursor_highlight()
            self._scroll_to_cursor()
        self.focus()

    def on_project_header_pressed(self, message: ProjectHeader.Pressed) -> None:
        """Handle click on a project header — cursor move only."""
        idx = self._find_nav_index(message.header)
        if idx >= 0:
            self.cursor_index = idx
            self._update_cursor_highlight()
            self._scroll_to_cursor()
        self.focus()
