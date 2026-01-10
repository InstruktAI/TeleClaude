"""Sessions view - shows running AI sessions."""

from __future__ import annotations

import asyncio
import curses
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui.pane_manager import ComputerInfo, TmuxPaneManager
from teleclaude.cli.tui.theme import AGENT_COLORS
from teleclaude.cli.tui.tree import TreeNode, build_tree
from teleclaude.cli.tui.views.base import ScrollableViewMixin
from teleclaude.cli.tui.widgets.modal import ConfirmModal, StartSessionModal

if TYPE_CHECKING:
    from teleclaude.cli.tui.app import FocusContext

logger = get_logger(__name__)


def _relative_time(iso_timestamp: str | None) -> str:
    """Convert ISO timestamp to relative time string.

    Args:
        iso_timestamp: ISO 8601 timestamp string or None

    Returns:
        Relative time like "5m ago", "1h ago", "2d ago"
    """
    if not iso_timestamp:
        return ""
    try:
        # Parse ISO timestamp
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt

        seconds = int(diff.total_seconds())
        if seconds < 60:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except (ValueError, TypeError):
        return ""


class SessionsView(ScrollableViewMixin):
    """View 1: Sessions - project-centric tree with AI-to-AI nesting."""

    def __init__(
        self,
        api: object,
        agent_availability: dict[str, dict[str, object]],  # guard: loose-dict
        focus: FocusContext,
        pane_manager: TmuxPaneManager,
    ):
        """Initialize sessions view.

        Args:
            api: API client instance
            agent_availability: Agent availability status
            focus: Shared focus context
            pane_manager: Tmux pane manager for session preview
        """
        self.api = api
        self.agent_availability = agent_availability
        self.focus = focus
        self.pane_manager = pane_manager
        self.tree: list[TreeNode] = []
        self.flat_items: list[TreeNode] = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.collapsed_sessions: set[str] = set()  # Session IDs that are collapsed
        # State tracking for color coding (detect changes between refreshes)
        self._prev_state: dict[str, dict[str, str]] = {}  # session_id -> {input, output}
        self._active_field: dict[str, str] = {}  # session_id -> "input" | "output" | "none"
        # Store sessions for child lookup
        self._sessions: list[dict[str, object]] = []  # guard: loose-dict
        # Store computers for SSH connection lookup
        self._computers: list[dict[str, object]] = []  # guard: loose-dict
        # Row-to-item mapping for mouse click handling (built during render)
        self._row_to_item: dict[int, int] = {}
        # Signal for app to trigger data refresh
        self.needs_refresh: bool = False
        # Visible height for scroll calculations (updated during render)
        self._visible_height: int = 20  # Default, updated in render
        # Track rendered item range for scroll calculations
        self._last_rendered_range: tuple[int, int] = (0, 0)

    async def refresh(
        self,
        computers: list[dict[str, object]],  # guard: loose-dict
        projects: list[dict[str, object]],  # guard: loose-dict
        sessions: list[dict[str, object]],  # guard: loose-dict
    ) -> None:
        """Refresh view data.

        Args:
            computers: List of computers
            projects: List of projects
            sessions: List of sessions
        """
        logger.debug(
            "SessionsView.refresh: %d computers, %d projects, %d sessions",
            len(computers),
            len(projects),
            len(sessions),
        )

        # Store sessions for child lookup
        self._sessions = sessions
        # Store computers for SSH connection lookup
        self._computers = computers

        # Track state changes for color coding
        self._update_activity_state(sessions)

        self.tree = build_tree(computers, projects, sessions)
        logger.debug("Tree built with %d root nodes", len(self.tree))
        self.rebuild_for_focus()

    def _update_activity_state(self, sessions: list[dict[str, object]]) -> None:  # guard: loose-dict
        """Update activity state tracking for color coding.

        Determines which field (input/output) is "active" (bright) based on changes.
        Activity older than 60 seconds is considered idle regardless of changes.

        Args:
            sessions: List of session dicts
        """
        now = datetime.now(timezone.utc)
        idle_threshold_seconds = 60

        for session in sessions:
            session_id = str(session.get("session_id", ""))
            if not session_id:
                continue

            curr_input = str(session.get("last_input") or "")
            curr_output = str(session.get("last_output") or "")

            # Check if last_activity is older than threshold
            last_activity_str = str(session.get("last_activity") or "")
            is_idle_by_time = True  # Default to idle if we can't parse or missing
            if last_activity_str:
                try:
                    last_activity_dt = datetime.fromisoformat(last_activity_str.replace("Z", "+00:00"))
                    # Ensure timezone-aware comparison
                    if last_activity_dt.tzinfo is None:
                        last_activity_dt = last_activity_dt.replace(tzinfo=timezone.utc)
                    age_seconds = (now - last_activity_dt).total_seconds()
                    # Treat negative ages (timezone mismatch) or old activity as idle
                    is_idle_by_time = age_seconds > idle_threshold_seconds or age_seconds < 0
                except (ValueError, TypeError):
                    pass  # Keep default of idle

            # If activity is old or unparseable, always show as idle
            if is_idle_by_time:
                self._active_field[session_id] = "none"
                self._prev_state[session_id] = {"input": curr_input, "output": curr_output}
                continue

            # Activity is recent - check if this is a NEW session (no previous state)
            prev = self._prev_state.get(session_id)
            if prev is None:
                # First time seeing this session with recent activity
                # Show output as highlighted if present, otherwise input, otherwise idle
                if curr_output:
                    self._active_field[session_id] = "output"
                elif curr_input:
                    self._active_field[session_id] = "input"
                else:
                    self._active_field[session_id] = "none"
                self._prev_state[session_id] = {"input": curr_input, "output": curr_output}
                continue

            # Existing session - check what changed
            prev_input = prev.get("input", "")
            prev_output = prev.get("output", "")

            input_changed = curr_input != prev_input
            output_changed = curr_output != prev_output

            if output_changed:
                # New output → output is bright (AI just responded)
                self._active_field[session_id] = "output"
            elif input_changed:
                # New input → input is bright (processing)
                self._active_field[session_id] = "input"
            # Note: Don't set to "none" here - keep previous active state
            # until it becomes idle by time threshold

            # Store current state for next comparison
            self._prev_state[session_id] = {"input": curr_input, "output": curr_output}

    def rebuild_for_focus(self) -> None:
        """Rebuild flat_items based on current focus context."""
        logger.debug(
            "SessionsView.rebuild_for_focus: focus.computer=%s, focus.project=%s",
            self.focus.computer,
            self.focus.project,
        )

        # Start from root and filter based on focus
        nodes = self.tree

        # If focused on a computer, filter to that computer's children
        if self.focus.computer:
            for node in self.tree:
                if node.type == "computer" and node.data.get("name") == self.focus.computer:
                    nodes = node.children
                    logger.debug("Filtered to computer '%s': %d children", self.focus.computer, len(nodes))
                    break
            else:
                nodes = []  # Computer not found
                logger.warning("Computer '%s' not found in tree", self.focus.computer)

        # If also focused on a project, filter to that project's children
        if self.focus.project and nodes:
            for node in nodes:
                if node.type == "project" and node.data.get("path") == self.focus.project:
                    nodes = node.children
                    logger.debug("Filtered to project '%s': %d children", self.focus.project, len(nodes))
                    break
            else:
                nodes = []  # Project not found
                logger.warning("Project '%s' not found in tree", self.focus.project)

        self.flat_items = self._flatten_tree(nodes, base_depth=0)
        logger.debug("Flattened to %d items", len(self.flat_items))

        # Reset selection if out of bounds
        if self.selected_index >= len(self.flat_items):
            self.selected_index = max(0, len(self.flat_items) - 1)
        self.scroll_offset = 0

    def _flatten_tree(self, nodes: list[TreeNode], base_depth: int = 0) -> list[TreeNode]:
        """Flatten tree for navigation.

        Args:
            nodes: Tree nodes
            base_depth: Base depth offset for rendering

        Returns:
            Flattened list of nodes with adjusted depth
        """
        result: list[TreeNode] = []
        for node in nodes:
            # Create a shallow copy with adjusted depth for display
            display_node = TreeNode(
                type=node.type,
                data=node.data,
                depth=base_depth,
                children=node.children,
                parent=node.parent,
            )
            result.append(display_node)
            result.extend(self._flatten_tree(node.children, base_depth + 1))
        return result

    def get_action_bar(self) -> str:
        """Return action bar string based on selected item type.

        Returns:
            Context-appropriate action bar text
        """
        back_hint = "[←] Back  " if self.focus.stack else ""

        if not self.flat_items or self.selected_index >= len(self.flat_items):
            return back_hint.strip() if back_hint else ""

        selected = self.flat_items[self.selected_index]
        if selected.type == "session":
            # Show toggle state in action bar
            tmux_session = str(selected.data.get("tmux_session_name") or "")
            is_previewing = self.pane_manager.active_session == tmux_session
            preview_action = "[Enter] Hide Preview" if is_previewing else "[Enter] Preview"
            return f"{back_hint}{preview_action}  [←/→] Collapse/Expand  [k] Kill"
        if selected.type == "project":
            return f"{back_hint}[n] Untitled"
        # computer
        return f"{back_hint}[→] View Projects"

    # move_up() and move_down() inherited from ScrollableViewMixin

    def drill_down(self) -> bool:
        """Drill down into selected item (arrow right).

        For computers: navigate into them (show projects).
        For projects: do nothing - sessions are already visible as children.
        For sessions: expand to show input/output.

        Returns:
            True if action taken, False if not possible
        """
        if not self.flat_items or self.selected_index >= len(self.flat_items):
            logger.debug("drill_down: no items or invalid index")
            return False

        item = self.flat_items[self.selected_index]
        logger.debug("drill_down: item.type=%s", item.type)

        if item.type == "computer":
            self.focus.push("computer", str(item.data.get("name", "")))
            self.rebuild_for_focus()
            self.selected_index = 0
            logger.debug("drill_down: pushed computer focus")
            return True
        if item.type == "session":
            # Expand this session (if not already expanded)
            session_id = str(item.data.get("session_id", ""))
            if session_id in self.collapsed_sessions:
                self.collapsed_sessions.discard(session_id)
                logger.debug("drill_down: expanded session %s", session_id[:8])
                return True
            logger.debug("drill_down: session already expanded")
            return False  # Already expanded
        # Projects don't drill down - sessions are visible as children
        logger.debug("drill_down: no action for type=%s", item.type)
        return False

    def collapse_selected(self) -> bool:
        """Collapse selected session (arrow left on session).

        Returns:
            True if collapsed, False if not a session or already collapsed
        """
        if not self.flat_items or self.selected_index >= len(self.flat_items):
            logger.debug("collapse_selected: no items or invalid index")
            return False

        item = self.flat_items[self.selected_index]
        logger.debug("collapse_selected: item.type=%s", item.type)

        if item.type == "session":
            session_id = str(item.data.get("session_id", ""))
            if session_id not in self.collapsed_sessions:
                self.collapsed_sessions.add(session_id)
                logger.debug("collapse_selected: collapsed session %s", session_id[:8])
                return True
            logger.debug("collapse_selected: session already collapsed")
            return False  # Already collapsed - let navigation take over
        logger.debug("collapse_selected: not a session, returning False")
        return False

    def expand_all(self) -> None:
        """Expand all sessions (show input/output)."""
        logger.debug("expand_all: clearing collapsed_sessions (was %d)", len(self.collapsed_sessions))
        self.collapsed_sessions.clear()

    def collapse_all(self) -> None:
        """Collapse all sessions (hide input/output)."""
        logger.debug("collapse_all: collecting all session IDs")
        self._collect_all_session_ids(self.tree)
        logger.debug("collapse_all: collapsed_sessions now has %d entries", len(self.collapsed_sessions))

    def _collect_all_session_ids(self, nodes: list[TreeNode]) -> None:
        """Recursively collect all session IDs into collapsed_sessions.

        Args:
            nodes: Tree nodes to scan
        """
        for node in nodes:
            if node.type == "session":
                session_id = str(node.data.get("session_id", ""))
                self.collapsed_sessions.add(session_id)
            if node.children:
                self._collect_all_session_ids(node.children)

    def handle_enter(self, stdscr: object) -> None:
        """Handle Enter key - perform action on selected item.

        Args:
            stdscr: Curses screen object
        """
        if not self.flat_items:
            return
        item = self.flat_items[self.selected_index]

        if item.type == "computer":
            # Drill down into computer (same as right arrow)
            self.drill_down()
        elif item.type == "project":
            # Start new session on project
            self._start_session_for_project(stdscr, item.data)
        elif item.type == "session":
            # Toggle session preview pane
            self._toggle_session_pane(item)

    def _get_computer_info(self, computer_name: str) -> ComputerInfo | None:
        """Get SSH connection info for a computer.

        Args:
            computer_name: Computer name to look up

        Returns:
            ComputerInfo with user/host for SSH, or None if not found
        """
        for comp in self._computers:
            if comp.get("name") == computer_name:
                return ComputerInfo(
                    name=computer_name,
                    user=comp.get("user"),  # type: ignore[arg-type]
                    host=comp.get("host"),  # type: ignore[arg-type]
                )
        return None

    def _toggle_session_pane(self, item: TreeNode) -> None:
        """Toggle session preview pane visibility.

        Args:
            item: Session node
        """
        session = item.data
        session_id = str(session.get("session_id", ""))
        tmux_session = str(session.get("tmux_session_name") or "")
        computer_name = str(session.get("computer", "local"))

        logger.debug(
            "_toggle_session_pane: session_id=%s, tmux=%s, computer=%s",
            session_id[:8] if session_id else "?",
            tmux_session or "MISSING",
            computer_name,
        )

        if not tmux_session:
            logger.warning("_toggle_session_pane: tmux_session_name missing, cannot toggle")
            return

        # Get computer info for SSH (if remote)
        computer_info = self._get_computer_info(computer_name)
        logger.debug(
            "_toggle_session_pane: computer_info=%s (is_remote=%s)",
            computer_info.name if computer_info else "None",
            computer_info.is_remote if computer_info else "N/A",
        )

        # Look for child sessions (sessions where initiator_session_id == this session's id)
        child_tmux_session: str | None = None
        for sess in self._sessions:
            if sess.get("initiator_session_id") == session_id:
                child_tmux = sess.get("tmux_session_name")
                if child_tmux:
                    child_tmux_session = str(child_tmux)
                    break

        # Toggle pane visibility (handles both local and remote via SSH)
        self.pane_manager.toggle_session(tmux_session, child_tmux_session, computer_info)

    def _start_session_for_project(self, stdscr: object, project: dict[str, object]) -> None:  # guard: loose-dict
        """Open modal to start session on project.

        Args:
            stdscr: Curses screen object
            project: Project data
        """
        # Use project's computer field, fallback to focused computer, then "local"
        computer_value = project.get("computer") or self.focus.computer or "local"
        logger.info(
            "_start_session_for_project: project_computer=%s, focus_computer=%s, resolved=%s",
            project.get("computer"),
            self.focus.computer,
            computer_value,
        )
        modal = StartSessionModal(
            computer=str(computer_value),
            project_path=str(project.get("path", "")),
            api=self.api,
            agent_availability=self.agent_availability,
        )
        result = modal.run(stdscr)
        if result:
            # Session started - trigger auto-refresh
            self.needs_refresh = True

    def handle_key(self, key: int, stdscr: object) -> None:
        """Handle view-specific keys.

        Args:
            key: Key code
            stdscr: Curses screen object
        """
        key_char = chr(key) if 32 <= key < 127 else f"({key})"
        logger.debug("SessionsView.handle_key: key=%s (%d)", key_char, key)

        # Global expand/collapse (works even with no selection)
        if key == ord("+") or key == ord("="):  # = for convenience (shift not needed)
            logger.debug("handle_key: expand_all triggered")
            self.expand_all()
            return
        if key == ord("-"):
            logger.debug("handle_key: collapse_all triggered")
            self.collapse_all()
            return

        if not self.flat_items or self.selected_index >= len(self.flat_items):
            logger.debug("handle_key: no items or invalid index, ignoring key")
            return

        selected = self.flat_items[self.selected_index]
        logger.debug("handle_key: selected.type=%s", selected.type)

        if key == ord("n"):
            # Start new session - only on project
            if selected.type == "project":
                logger.debug("handle_key: starting new session on project")
                self._start_session_for_project(stdscr, selected.data)
            else:
                logger.debug("handle_key: 'n' ignored, not on a project")
            return

        if key == ord("k"):
            # Kill selected session
            if selected.type != "session":
                logger.debug("handle_key: 'k' ignored, not on a session")
                return  # Only kill sessions, not computers/projects

            session_id = str(selected.data.get("session_id", ""))
            computer = str(selected.data.get("computer", ""))
            title = str(selected.data.get("title", "Unknown"))

            # Confirm kill with modal
            modal = ConfirmModal(
                title="Kill Session",
                message="Are you sure you want to kill this session?",
                details=[
                    f"Title: {title}",
                    f"Computer: {computer}",
                    f"Session ID: {session_id[:16]}...",
                ],
            )
            if not modal.run(stdscr):
                return  # Cancelled

            try:
                result = asyncio.get_event_loop().run_until_complete(
                    self.api.end_session(session_id=session_id, computer=computer)  # type: ignore[attr-defined]
                )
                if result:
                    self.needs_refresh = True
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Error killing session: %s", e)

    def handle_click(self, screen_row: int) -> bool:
        """Handle mouse click at screen row.

        Args:
            screen_row: The screen row that was clicked

        Returns:
            True if an item was selected, False otherwise
        """
        item_idx = self._row_to_item.get(screen_row)
        if item_idx is not None:
            self.selected_index = item_idx
            return True
        return False

    def render(self, stdscr: object, start_row: int, height: int, width: int) -> None:
        """Render view content with scrolling support.

        Args:
            stdscr: Curses screen object
            start_row: Starting row
            height: Available height
            width: Screen width
        """
        # Store visible height for scroll calculations
        self._visible_height = height

        logger.debug(
            "SessionsView.render: start_row=%d, height=%d, width=%d, flat_items=%d, scroll=%d",
            start_row,
            height,
            width,
            len(self.flat_items),
            self.scroll_offset,
        )

        # Clear row-to-item mapping (rebuilt each render)
        self._row_to_item.clear()

        if not self.flat_items:
            msg = "(no items)"
            logger.debug("render: no items to display")
            stdscr.addstr(start_row, 2, msg, curses.A_DIM)  # type: ignore[attr-defined]
            return

        # Clamp scroll_offset to valid range
        max_scroll = max(0, len(self.flat_items) - height + 3)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))

        row = start_row
        items_rendered = 0
        first_rendered = self.scroll_offset
        last_rendered = self.scroll_offset
        for i, item in enumerate(self.flat_items):
            # Skip items before scroll offset
            if i < self.scroll_offset:
                continue
            if row >= start_row + height:
                logger.debug("render: stopped at row %d (out of space), rendered %d items", row, items_rendered)
                break  # No more space

            last_rendered = i
            is_selected = i == self.selected_index
            lines_used = self._render_item(stdscr, row, item, width, is_selected)
            # Map all lines of this item to its index (for mouse click)
            for offset in range(lines_used):
                self._row_to_item[row + offset] = i
            row += lines_used
            items_rendered += 1

        # Track rendered range for scroll calculations
        self._last_rendered_range = (first_rendered, last_rendered)

        logger.debug(
            "render: rendered %d of %d items (scroll_offset=%d)",
            items_rendered,
            len(self.flat_items),
            self.scroll_offset,
        )

    def _render_item(self, stdscr: object, row: int, item: TreeNode, width: int, selected: bool) -> int:
        """Render a single tree item.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            item: Tree node
            width: Screen width
            selected: Whether this item is selected

        Returns:
            Number of lines used
        """
        indent = "  " * item.depth
        attr = curses.A_REVERSE if selected else 0

        if item.type == "computer":
            line = f"{indent}🖥  {item.data.get('name', '')}"
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
            return 1
        if item.type == "project":
            path = str(item.data.get("path", ""))
            session_count = len(item.children)
            suffix = f"({session_count})" if session_count else ""
            line = f"{indent}📁 {path} {suffix}"
            # Mute empty projects
            if not session_count and not selected:
                attr = curses.A_DIM
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
            return 1
        if item.type == "session":
            return self._render_session(stdscr, row, item, width, selected)
        return 1

    def _render_session(self, stdscr: object, row: int, item: TreeNode, width: int, selected: bool) -> int:
        """Render session with agent-colored text (1-3 lines).

        Color coding rules:
        - Input bright + Output muted/none = processing input
        - Input muted + Output bright = AI just responded
        - Both muted = idle (no changes on refresh)

        Args:
            stdscr: Curses screen object
            row: Row to render at
            item: Session node
            width: Screen width
            selected: Whether this item is selected

        Returns:
            Number of lines used (1-3 depending on content and collapsed state)
        """
        session = item.data
        session_id = str(session.get("session_id", ""))
        is_collapsed = session_id in self.collapsed_sessions

        indent = "  " * item.depth
        agent = str(session.get("active_agent") or "?")
        mode = str(session.get("thinking_mode", "?"))
        title = str(session.get("title", "Untitled"))
        idx = str(session.get("display_index", "?"))

        # Get agent color pairs (muted, normal, highlight)
        agent_colors = AGENT_COLORS.get(agent, {"muted": 0, "normal": 0, "highlight": 0})
        muted_pair = agent_colors.get("muted", 0)
        normal_pair = agent_colors.get("normal", 0)
        highlight_pair = agent_colors.get("highlight", 0)
        muted_attr = curses.color_pair(muted_pair) if muted_pair else curses.A_DIM
        normal_attr = curses.color_pair(normal_pair) if normal_pair else 0
        highlight_attr = curses.color_pair(highlight_pair) if highlight_pair else curses.A_BOLD

        # Title line uses normal color (the original agent color)
        title_attr = curses.A_REVERSE if selected else normal_attr

        # Collapse indicator
        collapse_indicator = "▶" if is_collapsed else "▼"

        # Relative time
        last_activity = str(session.get("last_activity") or "")
        rel_time = _relative_time(last_activity)
        time_suffix = f"  {rel_time}" if rel_time else ""

        # Line 1: [idx] ▶/▼ agent/mode "title" Xm ago
        line1 = f'{indent}[{idx}] {collapse_indicator} {agent}/{mode}  "{title}"{time_suffix}'
        try:
            stdscr.addstr(row, 0, line1[:width], title_attr)  # type: ignore[attr-defined]
        except curses.error as e:
            logger.warning("curses error rendering session title at row %d: %s", row, e)

        # If collapsed, only show title line
        if is_collapsed:
            return 1

        lines_used = 1

        # Calculate content indent (align with agent name)
        # indent + "[X] ▶ " = where agent starts
        content_indent = indent + "      "  # 6 chars for "[X] ▶ "

        # Line 2 (expanded only): ID: <full_session_id>
        line2 = f"{content_indent}ID: {session_id}"
        try:
            stdscr.addstr(row + lines_used, 0, line2[:width], normal_attr)  # type: ignore[attr-defined]
        except curses.error as e:
            logger.warning("curses error rendering session ID at row %d: %s", row + lines_used, e)
        lines_used += 1

        # Determine which field is "active" (highlight) based on state tracking
        active = self._active_field.get(session_id, "none")
        input_attr = highlight_attr if active == "input" else muted_attr
        output_attr = highlight_attr if active == "output" else muted_attr

        # Line 3: Last input (only if content exists)
        last_input = str(session.get("last_input") or "").strip()
        if last_input:
            input_text = last_input.replace("\n", " ")[:60]
            line3 = f"{content_indent}last input: {input_text}"
            try:
                stdscr.addstr(row + lines_used, 0, line3[:width], input_attr)  # type: ignore[attr-defined]
            except curses.error as e:
                logger.warning("curses error rendering session input at row %d: %s", row + lines_used, e)
            lines_used += 1

        # Line 4: Last output (only if content exists)
        last_output = str(session.get("last_output") or "").strip()
        if last_output:
            output_text = last_output.replace("\n", " ")[:60]
            line4 = f"{content_indent}last output: {output_text}"
            try:
                stdscr.addstr(row + lines_used, 0, line4[:width], output_attr)  # type: ignore[attr-defined]
            except curses.error as e:
                logger.warning("curses error rendering session output at row %d: %s", row + lines_used, e)
            lines_used += 1

        return lines_used
