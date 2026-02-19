"""Sessions view with hierarchical tree display."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.models import ComputerInfo, ProjectInfo, SessionInfo
from teleclaude.cli.tui.messages import (
    CreateSessionRequest,
    FocusPaneRequest,
    KillSessionRequest,
    PreviewChanged,
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
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.modals import ConfirmModal, StartSessionModal
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.session_row import SessionRow

if TYPE_CHECKING:
    from teleclaude.cli.models import AgentAvailabilityInfo
    from teleclaude.cli.tui.tree import TreeNode


# Double-press detection threshold (seconds)
DOUBLE_PRESS_THRESHOLD = 0.65
MAX_STICKY = 5


class SessionsView(Widget):
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
        ("up", "cursor_up", "Previous"),
        ("down", "cursor_down", "Next"),
        ("space", "toggle_preview", "Preview/Sticky"),
        ("enter", "focus_pane", "Focus pane"),
        ("left", "collapse", "Collapse"),
        ("right", "expand", "Expand"),
        ("plus", "expand_all", "Expand all"),
        ("minus", "collapse_all", "Collapse all"),
        ("n", "new_session", "New session"),
        ("k", "kill_session", "Kill session"),
        ("r", "restart_session", "Restart session"),
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
        self._last_output_summary: dict[str, str] = {}
        self._collapsed_sessions: set[str] = set()
        # Double-press detection for Space
        self._last_space_time: float = 0.0
        self._last_space_session: str | None = None
        # Flat list of navigable widgets for keyboard nav
        self._nav_items: list[Widget] = []

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="sessions-scroll")

    def update_data(
        self,
        computers: list[ComputerInfo],
        projects: list[ProjectInfo],
        sessions: list[SessionInfo],
        availability: dict[str, AgentAvailabilityInfo] | None = None,
    ) -> None:
        """Update view with fresh API data and rebuild tree."""
        self._computers = computers
        self._projects = projects
        self._sessions = sessions
        if availability is not None:
            self._availability = availability
        self._rebuild_tree()

    def load_persisted_state(
        self,
        sticky_ids: list[str],
        input_highlights: set[str],
        output_highlights: set[str],
        last_output_summary: dict[str, str],
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

    def _rebuild_tree(self) -> None:
        """Rebuild the tree display from current data."""
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

        # Restore cursor position
        if self._nav_items and self.cursor_index >= len(self._nav_items):
            self.cursor_index = max(0, len(self._nav_items) - 1)
        self._update_cursor_highlight()

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

        elif is_session_node(node):
            session_data: SessionDisplayInfo = node.data
            session = session_data.session
            row = SessionRow(
                session=session,
                display_index=session_data.display_index,
                depth=node.depth - 1,
            )
            # Apply persisted/reactive state
            row.collapsed = session.session_id not in self._collapsed_sessions
            row.is_sticky = session.session_id in self._sticky_session_ids
            row.is_preview = session.session_id == self.preview_session_id

            # Apply highlights
            if session.session_id in self._input_highlights:
                row.highlight_type = "input"
            elif session.session_id in self._output_highlights:
                row.highlight_type = "output"

            # Apply output summary
            summary = self._last_output_summary.get(session.session_id, "")
            if summary:
                row.last_output_summary = summary

            container.mount(row)
            self._nav_items.append(row)

            # Recurse into AI-to-AI children
            for child in node.children:
                self._mount_node(container, child)

    def _update_cursor_highlight(self) -> None:
        """Update the selected class on the current nav item."""
        for i, widget in enumerate(self._nav_items):
            widget.set_class(i == self.cursor_index, "selected")

    def _current_session_row(self) -> SessionRow | None:
        """Get the SessionRow at the current cursor position, if any."""
        if not self._nav_items or self.cursor_index >= len(self._nav_items):
            return None
        item = self._nav_items[self.cursor_index]
        return item if isinstance(item, SessionRow) else None

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
        """Space: single press = preview, double press = toggle sticky."""
        row = self._current_session_row()
        if not row:
            return

        now = time.monotonic()
        session_id = row.session_id

        # Double-press detection
        if self._last_space_session == session_id and (now - self._last_space_time) < DOUBLE_PRESS_THRESHOLD:
            # Double press -> toggle sticky
            self._toggle_sticky(session_id)
            self._last_space_time = 0.0
            self._last_space_session = None
            return

        self._last_space_time = now
        self._last_space_session = session_id

        # Single press -> preview
        if self.preview_session_id == session_id:
            self.preview_session_id = None
        else:
            self.preview_session_id = session_id

        # Clear highlights on preview
        self._input_highlights.discard(session_id)
        self._output_highlights.discard(session_id)
        row.highlight_type = ""

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
        """Enter: focus the tmux pane for the selected session."""
        row = self._current_session_row()
        if not row:
            return
        self.post_message(FocusPaneRequest(row.session_id))

    def action_collapse(self) -> None:
        """Left: collapse selected session row."""
        row = self._current_session_row()
        if row and not row.collapsed:
            row.collapsed = True
            self._collapsed_sessions.discard(row.session_id)

    def action_expand(self) -> None:
        """Right: expand selected session row."""
        row = self._current_session_row()
        if row and row.collapsed:
            row.collapsed = False
            self._collapsed_sessions.add(row.session_id)

    def action_expand_all(self) -> None:
        """+ : expand all session rows."""
        for widget in self._nav_items:
            if isinstance(widget, SessionRow):
                widget.collapsed = False
                self._collapsed_sessions.add(widget.session_id)

    def action_collapse_all(self) -> None:
        """- : collapse all session rows."""
        for widget in self._nav_items:
            if isinstance(widget, SessionRow):
                widget.collapsed = True
        self._collapsed_sessions.clear()

    def action_new_session(self) -> None:
        """n: open new session modal."""
        # Find the project for the current cursor position
        row = self._current_session_row()
        if row and row.session:
            computer = row.session.computer or "local"
            project_path = row.session.project_path or ""
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

    # --- Reactive watchers ---

    def watch_preview_session_id(self, session_id: str | None) -> None:
        """When preview changes, update row highlights and notify PaneBridge."""
        for widget in self._nav_items:
            if isinstance(widget, SessionRow):
                widget.is_preview = widget.session_id == session_id
        self.post_message(PreviewChanged(session_id))

    # --- Session highlight management ---

    def set_input_highlight(self, session_id: str) -> None:
        """Mark session as having new input."""
        if session_id == self.preview_session_id:
            return
        self._input_highlights.add(session_id)
        self._output_highlights.discard(session_id)
        self._update_row_highlight(session_id, "input")

    def set_output_highlight(self, session_id: str, summary: str = "") -> None:
        """Mark session as having new output."""
        if session_id == self.preview_session_id:
            return
        self._output_highlights.add(session_id)
        self._input_highlights.discard(session_id)
        if summary:
            self._last_output_summary[session_id] = summary
        self._update_row_highlight(session_id, "output")

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
        """Set active tool display on a session row."""
        for widget in self._nav_items:
            if isinstance(widget, SessionRow) and widget.session_id == session_id:
                widget.active_tool = tool_info
                break

    # --- State export for persistence ---

    def get_persisted_state(self) -> dict[str, object]:  # guard: loose-dict
        """Export state for persistence."""
        return {
            "sticky_sessions": [{"session_id": sid} for sid in self._sticky_session_ids],
            "input_highlights": sorted(self._input_highlights),
            "output_highlights": sorted(self._output_highlights),
            "last_output_summary": dict(sorted(self._last_output_summary.items())),
            "collapsed_sessions": sorted(self._collapsed_sessions),
            "preview": {"session_id": self.preview_session_id} if self.preview_session_id else None,
        }
