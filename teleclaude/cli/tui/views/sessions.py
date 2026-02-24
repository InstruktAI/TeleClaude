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
    CreateSessionRequest,
    KillSessionRequest,
    PreviewChanged,
    RestartSessionsRequest,
    ReviveSessionRequest,
    StateDirty,
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
from teleclaude.cli.tui.views.interaction import TreeInteractionAction, TreeInteractionState
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.group_separator import GroupSeparator
from teleclaude.cli.tui.widgets.modals import ConfirmModal, StartSessionModal
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.session_row import SessionRow

if TYPE_CHECKING:
    from teleclaude.cli.models import AgentAvailabilityInfo
    from teleclaude.cli.tui.tree import TreeNode


# Double-press detection threshold (seconds)
DOUBLE_PRESS_THRESHOLD = 0.65
MAX_STICKY = 5
# Auto-clear highlights on preview session after this many seconds
PREVIEW_HIGHLIGHT_DURATION = 3.0


class SessionsView(Widget, can_focus=True):
    """Sessions tab view with hierarchical tree and keyboard navigation.

    Handles: arrow nav, Space (preview/sticky), Enter (focus pane),
    Left/Right (collapse/expand), +/- (expand/collapse all),
    n (new session), k (kill session).
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
        Binding("up", "cursor_up", "Up", key_display="↑", group=Binding.Group("Nav", compact=True)),
        Binding("down", "cursor_down", "Down", key_display="↓", group=Binding.Group("Nav", compact=True)),
        Binding("space", "toggle_preview", "Preview/Sticky"),
        Binding("enter", "focus_pane", "Focus"),
        Binding("left", "collapse", "Collapse", key_display="←", group=Binding.Group("Fold", compact=True)),
        Binding("right", "expand", "Expand", key_display="→", group=Binding.Group("Fold", compact=True)),
        Binding("equals_sign", "expand_all", "All", key_display="+", group=Binding.Group("Fold", compact=True)),
        Binding("minus", "collapse_all", "None", key_display="-", group=Binding.Group("Fold", compact=True)),
        Binding("n", "new_session", "New"),
        Binding("k", "kill_session", "Kill"),
        Binding("R", "restart_session", "Restart"),
        Binding("R", "restart_all", "Restart All"),
    ]

    preview_session_id = reactive[str | None](None)
    cursor_index = reactive(0)

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
        old_ids = {s.session_id for s in self._sessions}
        new_ids = {s.session_id for s in sessions}
        self._computers = computers
        self._projects = projects
        self._sessions = sessions
        if availability is not None:
            self._availability = availability

        # Prune stale session IDs from sticky/preview state
        stale_sticky = [sid for sid in self._sticky_session_ids if sid not in new_ids]
        if stale_sticky:
            self._logger.info("Pruning %d stale sticky IDs: %s", len(stale_sticky), [s[:8] for s in stale_sticky])
            self._sticky_session_ids = [sid for sid in self._sticky_session_ids if sid in new_ids]
        if self.preview_session_id and self.preview_session_id not in new_ids:
            self._logger.info("Pruning stale preview ID: %s", self.preview_session_id[:8])
            self.preview_session_id = None

        if old_ids != new_ids or not self._nav_items:
            # Session list changed — full rebuild (includes _apply_pending_selection)
            self._rebuild_tree()
        else:
            # Same sessions — just update data on existing rows
            session_map = {s.session_id: s for s in sessions}
            for widget in self._nav_items:
                if isinstance(widget, SessionRow) and widget.session_id in session_map:
                    widget.update_session(session_map[widget.session_id])
            # Session data updated — pending session may now have a tmux pane
            self._apply_pending_selection()

    def load_persisted_state(
        self,
        sticky_ids: list[str],
        input_highlights: set[str],
        output_highlights: set[str],
        last_output_summary: dict[str, dict[str, object]],  # guard: loose-dict
        collapsed_sessions: set[str],
        preview_session_id: str | None,
    ) -> None:
        """Restore persisted state from state_store."""
        self._sticky_session_ids = sticky_ids
        self._input_highlights = input_highlights
        self._output_highlights = output_highlights
        self._last_output_summary = last_output_summary
        self._collapsed_sessions = collapsed_sessions
        if preview_session_id:
            self.preview_session_id = preview_session_id

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
                return

        # Not in tree yet — keep pending

    def _rebuild_tree(self) -> None:
        """Rebuild the tree display from current data."""
        _rt0 = time.monotonic()
        self._logger.trace("[PERF] SessionsView._rebuild_tree START t=%.3f", _rt0)
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

        tree = build_tree(computer_display, self._projects, self._sessions)

        for node in tree:
            self._mount_node(container, node)

        # Mark last-child sessions: a session uses └ when the next session
        # in the flat list is at a shallower depth (subtree closing).
        session_rows = [w for w in self._nav_items if isinstance(w, SessionRow)]
        for i, row in enumerate(session_rows):
            if i + 1 < len(session_rows):
                row.is_last_child = session_rows[i + 1].depth < row.depth
            # Last session in group is handled by skip_bottom_connector

        # Restore cursor position
        if self._nav_items and self.cursor_index >= len(self._nav_items):
            self.cursor_index = max(0, len(self._nav_items) - 1)

        # On first build, position cursor at the preview session row
        if not self._initial_cursor_positioned and self.preview_session_id:
            for i, widget in enumerate(self._nav_items):
                if isinstance(widget, SessionRow) and widget.session_id == self.preview_session_id:
                    self.cursor_index = i
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
        """Clear input/output highlights and active tool for a session."""
        self._cancel_highlight_timer(session_id)
        self._input_highlights.discard(session_id)
        self._output_highlights.discard(session_id)
        for widget in self._nav_items:
            if isinstance(widget, SessionRow) and widget.session_id == session_id:
                widget.highlight_type = ""
                widget.active_tool = ""
                break

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
        """Auto-clear callback — remove highlights and active tool."""
        self._highlight_timers.pop(session_id, None)
        self._input_highlights.discard(session_id)
        self._output_highlights.discard(session_id)
        for widget in self._nav_items:
            if isinstance(widget, SessionRow) and widget.session_id == session_id:
                widget.highlight_type = ""
                widget.active_tool = ""
                break

    # --- Mouse click handling (widget-level Pressed messages) ---

    def on_session_row_pressed(self, message: SessionRow.Pressed) -> None:
        """Handle click on a session row.

        Single click: move cursor + preview with focus.
        Double click: toggle sticky.
        """
        row = message.session_row
        idx = self._find_nav_index(row)
        if idx < 0:
            return

        self.cursor_index = idx
        self._update_cursor_highlight()
        self._scroll_to_cursor()

        session_id = row.session_id
        now = time.monotonic()

        # Double-click detection
        if self._last_click_session == session_id and (now - self._last_click_time) < DOUBLE_PRESS_THRESHOLD:
            self._toggle_sticky(session_id)
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

    # --- Keyboard actions ---

    def action_cursor_up(self) -> None:
        if self._nav_items and self.cursor_index > 0:
            self.cursor_index -= 1
            self._update_cursor_highlight()
            self._scroll_to_cursor()

    def action_cursor_down(self) -> None:
        if self._nav_items and self.cursor_index < len(self._nav_items) - 1:
            self.cursor_index += 1
            self._update_cursor_highlight()
            self._scroll_to_cursor()

    def _scroll_to_cursor(self) -> None:
        """Scroll the current cursor item into view."""
        if self._nav_items and 0 <= self.cursor_index < len(self._nav_items):
            self._nav_items[self.cursor_index].scroll_visible()

    def action_toggle_preview(self) -> None:
        """Space: single press = preview (no focus), double press = toggle sticky.

        Uses TreeInteractionState for double-press detection with guard intervals.
        If session is headless, revive it first.
        """
        row = self._current_session_row()
        if not row:
            return

        # Headless sessions: revive instead of preview
        if self._is_headless(row):
            self._revive_headless(row)
            return

        now = time.monotonic()
        session_id = row.session_id
        is_sticky = session_id in self._sticky_session_ids

        decision = self._interaction.decide_preview_action(
            session_id,
            now,
            is_sticky=is_sticky,
            allow_sticky_toggle=True,
        )

        if decision.action == TreeInteractionAction.NONE:
            return

        if decision.action == TreeInteractionAction.PREVIEW:
            if session_id == self.preview_session_id:
                # Already previewed — toggle OFF
                self.preview_session_id = None
                self.post_message(PreviewChanged(None, request_focus=False))
            else:
                self.preview_session_id = session_id
                self._clear_session_highlights(session_id)
                self.post_message(PreviewChanged(session_id, request_focus=False))

        elif decision.action == TreeInteractionAction.TOGGLE_STICKY:
            self._toggle_sticky(session_id)
            if decision.clear_preview:
                self.preview_session_id = None
                self.post_message(PreviewChanged(None, request_focus=False))
            self._interaction.mark_double_press_guard(session_id, now)

        elif decision.action == TreeInteractionAction.CLEAR_STICKY_PREVIEW:
            self.preview_session_id = None
            self._clear_session_highlights(session_id)
            self.post_message(PreviewChanged(None, request_focus=False))

    def _toggle_sticky(self, session_id: str) -> None:
        """Toggle sticky status for a session."""
        if session_id in self._sticky_session_ids:
            self._sticky_session_ids.remove(session_id)
        else:
            if len(self._sticky_session_ids) >= MAX_STICKY:
                return
            self._sticky_session_ids.append(session_id)

        # Update all session rows
        for widget in self._nav_items:
            if isinstance(widget, SessionRow):
                widget.is_sticky = widget.session_id in self._sticky_session_ids

        self.post_message(StickyChanged(self._sticky_session_ids.copy()))

    def action_focus_pane(self) -> None:
        """Enter: on a session — preview AND focus the tmux pane.

        On a project/computer header — open new session modal.
        If session is headless, revive it first.
        """
        row = self._current_session_row()
        if not row:
            # On a project or computer header — open new session modal
            self.action_new_session()
            return

        # Headless sessions: revive instead of focus
        if self._is_headless(row):
            self._revive_headless(row)
            return

        session_id = row.session_id

        # Set preview
        self.preview_session_id = session_id

        # Clear highlights
        self._clear_session_highlights(session_id)

        # Post with request_focus=True — pane shows AND cursor transfers to it
        self.post_message(PreviewChanged(session_id, request_focus=True))

    def action_collapse(self) -> None:
        """Left: collapse selected session row."""
        row = self._current_session_row()
        if row and not row.collapsed:
            row.collapsed = True
            self._collapsed_sessions.discard(row.session_id)
            self.post_message(StateDirty())

    def action_expand(self) -> None:
        """Right: expand selected session row."""
        row = self._current_session_row()
        if row and row.collapsed:
            row.collapsed = False
            self._collapsed_sessions.add(row.session_id)
            self.post_message(StateDirty())

    def action_expand_all(self) -> None:
        """+ : expand all session rows."""
        for widget in self._nav_items:
            if isinstance(widget, SessionRow):
                widget.collapsed = False
                self._collapsed_sessions.add(widget.session_id)
        self.post_message(StateDirty())

    def action_collapse_all(self) -> None:
        """- : collapse all session rows."""
        for widget in self._nav_items:
            if isinstance(widget, SessionRow):
                widget.collapsed = True
        self._collapsed_sessions.clear()
        self.post_message(StateDirty())

    def _resolve_context_for_cursor(self) -> tuple[str, str] | None:
        """Resolve computer + project_path from the current cursor position.

        Walks from cursor upward through nav_items to find the nearest
        ProjectHeader and ComputerHeader.
        """
        if not self._nav_items or self.cursor_index >= len(self._nav_items):
            return None

        item = self._nav_items[self.cursor_index]

        # On a session row — use its session data
        if isinstance(item, SessionRow) and item.session:
            return (item.session.computer or "local", item.session.project_path or "")

        # On a project header — use its data, walk up for computer
        if isinstance(item, ProjectHeader):
            computer = "local"
            for i in range(self.cursor_index - 1, -1, -1):
                nav = self._nav_items[i]
                if isinstance(nav, ComputerHeader):
                    computer = nav.data.computer.name
                    break
            return (computer, item.project.path)

        # On a computer header — use first project under it
        if isinstance(item, ComputerHeader):
            computer = item.data.computer.name
            for i in range(self.cursor_index + 1, len(self._nav_items)):
                nav = self._nav_items[i]
                if isinstance(nav, ProjectHeader):
                    return (computer, nav.project.path)
                if isinstance(nav, ComputerHeader):
                    break
            # No project found under this computer — use first project
            if self._projects:
                return (computer, self._projects[0].path)

        return None

    def action_new_session(self) -> None:
        """n: open new session modal."""
        context = self._resolve_context_for_cursor()
        if context:
            computer, project_path = context
        elif self._projects:
            computer = self._projects[0].computer or "local"
            project_path = self._projects[0].path
        else:
            return

        modal = StartSessionModal(
            computer=computer,
            project_path=project_path,
            agent_availability=self._availability,
        )
        self.app.push_screen(modal, self._on_create_session_result)

    def _on_create_session_result(self, result: CreateSessionRequest | None) -> None:
        """Handle result from StartSessionModal."""
        if result:
            self.post_message(result)

    def action_kill_session(self) -> None:
        """k: kill selected session (with confirmation)."""
        row = self._current_session_row()
        if not row:
            return

        session_id = row.session_id
        computer = row.session.computer or "local"
        title = row.session.title or "(untitled)"

        modal = ConfirmModal(
            title="Kill Session",
            message=f"Kill session '{title}'?",
        )

        def on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self.post_message(KillSessionRequest(session_id, computer))

        self.app.push_screen(modal, on_confirm)

    def action_restart_session(self) -> None:
        """R: restart selected session."""
        row = self._current_session_row()
        if not row:
            return
        from teleclaude.cli.tui.messages import RestartSessionRequest

        self.post_message(RestartSessionRequest(row.session_id, row.session.computer or "local"))

    def action_restart_all(self) -> None:
        """R on computer header: restart all sessions on that computer."""
        item = self._current_item()
        if not isinstance(item, ComputerHeader):
            return

        computer = item.data.computer.name
        session_ids = sorted({s.session_id for s in self._sessions if (s.computer or "local") == computer})
        if not session_ids:
            self.app.notify(f"No sessions to restart on {computer}", severity="warning")
            return

        modal = ConfirmModal(
            title="Restart All Sessions",
            message=f"Restart {len(session_ids)} sessions on '{computer}'?",
        )

        def on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self.post_message(RestartSessionsRequest(computer=computer, session_ids=session_ids))

        self.app.push_screen(modal, on_confirm)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Enable/hide actions based on current tree node type."""
        del parameters
        item = self._current_item()

        if action == "new_session":
            return isinstance(item, ProjectHeader)
        if action in {"kill_session", "restart_session", "focus_pane", "toggle_preview"}:
            return isinstance(item, SessionRow)
        if action == "restart_all":
            return isinstance(item, ComputerHeader)
        return True

    def watch_cursor_index(self, _index: int) -> None:
        """Refresh key bindings when node context changes."""
        if self.is_attached:
            self.app.refresh_bindings()

    # --- Reactive watchers ---

    def watch_preview_session_id(self, old_session_id: str | None, new_session_id: str | None) -> None:
        """When preview changes, update row visual highlights.

        Cancels any pending auto-clear timer for the old preview session
        (its highlights should persist as a non-preview session).

        Does NOT post PreviewChanged — that's done explicitly by action
        handlers with the correct request_focus flag.
        """
        if old_session_id:
            self._cancel_highlight_timer(old_session_id)
        for widget in self._nav_items:
            if isinstance(widget, SessionRow):
                widget.is_preview = widget.session_id == new_session_id

    # --- Session highlight management ---

    def set_input_highlight(self, session_id: str) -> None:
        """Mark session as having new input.

        Preview sessions: show highlight briefly then auto-clear.
        Other sessions: highlight persists until user interaction.
        """
        self._input_highlights.add(session_id)
        self._output_highlights.discard(session_id)
        self._update_row_highlight(session_id, "input")
        if session_id == self.preview_session_id:
            self._schedule_highlight_clear(session_id)

    def set_output_highlight(self, session_id: str, summary: str = "") -> None:
        """Mark session as having new output.

        Preview sessions: show highlight briefly then auto-clear.
        Other sessions: highlight persists until user interaction.
        """
        self._output_highlights.add(session_id)
        self._input_highlights.discard(session_id)
        if summary:
            self._last_output_summary[session_id] = {
                "text": summary,
                "ts": time.monotonic(),
            }
            for widget in self._nav_items:
                if isinstance(widget, SessionRow) and widget.session_id == session_id:
                    widget.last_output_summary = summary
                    break
        self._update_row_highlight(session_id, "output")
        if session_id == self.preview_session_id:
            self._schedule_highlight_clear(session_id)

    def clear_highlight(self, session_id: str) -> None:
        """Clear highlight for a session."""
        self._input_highlights.discard(session_id)
        self._output_highlights.discard(session_id)
        self._update_row_highlight(session_id, "")

    def _update_row_highlight(self, session_id: str, highlight_type: str) -> None:
        """Update highlight type on a session row."""
        for widget in self._nav_items:
            if isinstance(widget, SessionRow) and widget.session_id == session_id:
                widget.highlight_type = highlight_type
                break

    def update_session(self, session: SessionInfo) -> None:
        """Update a single session row with new data."""
        for widget in self._nav_items:
            if isinstance(widget, SessionRow) and widget.session_id == session.session_id:
                widget.update_session(session)
                break

    def set_active_tool(self, session_id: str, tool_info: str) -> None:
        """Set active tool display on a session row.

        Also persists to _last_output_summary so the text survives reload.
        Preview sessions: auto-clear after timeout.
        Other sessions: persists until cleared by agent_stop/agent_input.
        """
        self._last_output_summary[session_id] = {
            "text": tool_info,
            "ts": time.monotonic(),
        }
        for widget in self._nav_items:
            if isinstance(widget, SessionRow) and widget.session_id == session_id:
                widget.active_tool = tool_info
                widget.last_output_summary = tool_info
                break
        if session_id == self.preview_session_id:
            self._schedule_highlight_clear(session_id)

    def clear_active_tool(self, session_id: str) -> None:
        """Clear active tool display for a session."""
        for widget in self._nav_items:
            if isinstance(widget, SessionRow) and widget.session_id == session_id:
                widget.active_tool = ""
                break

    # --- State export for persistence ---

    def get_persisted_state(self) -> dict[str, object]:  # guard: loose-dict
        """Export state for persistence."""
        return {
            "sticky_sessions": [{"session_id": sid} for sid in self._sticky_session_ids],
            "input_highlights": sorted(self._input_highlights),
            "output_highlights": sorted(self._output_highlights),
            "last_output_summary": {
                k: {"text": str(v.get("text", "")), "ts": float(v.get("ts", 0))}
                for k, v in sorted(self._last_output_summary.items())
                if v.get("text")
            },
            "collapsed_sessions": sorted(self._collapsed_sessions),
            "preview": {"session_id": self.preview_session_id} if self.preview_session_id else None,
        }
