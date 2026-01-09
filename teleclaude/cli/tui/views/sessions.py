"""Sessions view - shows running AI sessions."""

from __future__ import annotations

import asyncio
import curses
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from teleclaude.cli.tui.theme import AGENT_COLORS
from teleclaude.cli.tui.tree import TreeNode, build_tree
from teleclaude.cli.tui.widgets.modal import StartSessionModal

if TYPE_CHECKING:
    from teleclaude.cli.tui.app import FocusContext


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


class SessionsView:
    """View 1: Sessions - project-centric tree with AI-to-AI nesting."""

    def __init__(
        self,
        api: object,
        agent_availability: dict[str, dict[str, object]],  # guard: loose-dict
        focus: FocusContext,
    ):
        """Initialize sessions view.

        Args:
            api: API client instance
            agent_availability: Agent availability status
            focus: Shared focus context
        """
        self.api = api
        self.agent_availability = agent_availability
        self.focus = focus
        self.tree: list[TreeNode] = []
        self.flat_items: list[TreeNode] = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.collapsed_sessions: set[str] = set()  # Session IDs that are collapsed
        # State tracking for color coding (detect changes between refreshes)
        self._prev_state: dict[str, dict[str, str]] = {}  # session_id -> {input, output}
        self._active_field: dict[str, str] = {}  # session_id -> "input" | "output" | "none"

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
        # Track state changes for color coding
        self._update_activity_state(sessions)

        self.tree = build_tree(computers, projects, sessions)
        self.rebuild_for_focus()

    def _update_activity_state(self, sessions: list[dict[str, object]]) -> None:  # guard: loose-dict
        """Update activity state tracking for color coding.

        Determines which field (input/output) is "active" (bright) based on changes.

        Args:
            sessions: List of session dicts
        """
        for session in sessions:
            session_id = str(session.get("session_id", ""))
            if not session_id:
                continue

            curr_input = str(session.get("last_input") or "")
            curr_output = str(session.get("last_output") or "")

            prev = self._prev_state.get(session_id, {"input": "", "output": ""})
            prev_input = prev.get("input", "")
            prev_output = prev.get("output", "")

            # Determine what changed
            input_changed = curr_input != prev_input
            output_changed = curr_output != prev_output

            if output_changed:
                # New output → output is bright (AI just responded)
                self._active_field[session_id] = "output"
            elif input_changed:
                # New input → input is bright (processing)
                self._active_field[session_id] = "input"
            else:
                # Nothing changed → both muted (idle)
                self._active_field[session_id] = "none"

            # Store current state for next comparison
            self._prev_state[session_id] = {"input": curr_input, "output": curr_output}

    def rebuild_for_focus(self) -> None:
        """Rebuild flat_items based on current focus context."""
        # Start from root and filter based on focus
        nodes = self.tree

        # If focused on a computer, filter to that computer's children
        if self.focus.computer:
            for node in self.tree:
                if node.type == "computer" and node.data.get("name") == self.focus.computer:
                    nodes = node.children
                    break
            else:
                nodes = []  # Computer not found

        # If also focused on a project, filter to that project's children
        if self.focus.project and nodes:
            for node in nodes:
                if node.type == "project" and node.data.get("path") == self.focus.project:
                    nodes = node.children
                    break
            else:
                nodes = []  # Project not found

        self.flat_items = self._flatten_tree(nodes, base_depth=0)

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
            return f"{back_hint}[Enter] Attach  [←/→] Collapse/Expand  [k] Kill"
        if selected.type == "project":
            return f"{back_hint}[n] New Session"
        # computer
        return f"{back_hint}[→] View Projects"

    def move_up(self) -> None:
        """Move selection up."""
        self.selected_index = max(0, self.selected_index - 1)

    def move_down(self) -> None:
        """Move selection down."""
        self.selected_index = min(len(self.flat_items) - 1, self.selected_index + 1)

    def drill_down(self) -> bool:
        """Drill down into selected item (arrow right).

        For computers: navigate into them (show projects).
        For projects: do nothing - sessions are already visible as children.
        For sessions: expand to show input/output.

        Returns:
            True if action taken, False if not possible
        """
        if not self.flat_items or self.selected_index >= len(self.flat_items):
            return False

        item = self.flat_items[self.selected_index]

        if item.type == "computer":
            self.focus.push("computer", str(item.data.get("name", "")))
            self.rebuild_for_focus()
            self.selected_index = 0
            return True
        if item.type == "session":
            # Expand this session (if not already expanded)
            session_id = str(item.data.get("session_id", ""))
            if session_id in self.collapsed_sessions:
                self.collapsed_sessions.discard(session_id)
                return True
            return False  # Already expanded
        # Projects don't drill down - sessions are visible as children
        return False

    def collapse_selected(self) -> bool:
        """Collapse selected session (arrow left on session).

        Returns:
            True if collapsed, False if not a session or already collapsed
        """
        if not self.flat_items or self.selected_index >= len(self.flat_items):
            return False

        item = self.flat_items[self.selected_index]
        if item.type == "session":
            session_id = str(item.data.get("session_id", ""))
            if session_id not in self.collapsed_sessions:
                self.collapsed_sessions.add(session_id)
                return True
            return False  # Already collapsed - let navigation take over
        return False

    def expand_all(self) -> None:
        """Expand all sessions (show input/output)."""
        self.collapsed_sessions.clear()

    def collapse_all(self) -> None:
        """Collapse all sessions (hide input/output)."""
        self._collect_all_session_ids(self.tree)

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
            # Attach to session
            self._attach_to_session(stdscr, item)

    def _attach_to_session(self, stdscr: object, item: TreeNode) -> None:  # noqa: ARG002
        """Attach to a session (placeholder).

        Args:
            stdscr: Curses screen object
            item: Session node
        """
        # TODO: Implement tmux attach
        pass

    def _start_session_for_project(self, stdscr: object, project: dict[str, object]) -> None:  # guard: loose-dict
        """Open modal to start session on project.

        Args:
            stdscr: Curses screen object
            project: Project data
        """
        modal = StartSessionModal(
            computer=str(project.get("computer", "local")),
            project_path=str(project.get("path", "")),
            api=self.api,
            agent_availability=self.agent_availability,
        )
        result = modal.run(stdscr)
        if result:
            # Session started - user can press [r] to refresh and see it
            pass

    def handle_key(self, key: int, stdscr: object) -> None:
        """Handle view-specific keys.

        Args:
            key: Key code
            stdscr: Curses screen object
        """
        # Global expand/collapse (works even with no selection)
        if key == ord("+") or key == ord("="):  # = for convenience (shift not needed)
            self.expand_all()
            return
        if key == ord("-"):
            self.collapse_all()
            return

        if not self.flat_items or self.selected_index >= len(self.flat_items):
            return

        selected = self.flat_items[self.selected_index]

        if key == ord("n"):
            # Start new session - only on project
            if selected.type == "project":
                self._start_session_for_project(stdscr, selected.data)
            return

        if key == ord("k"):
            # Kill selected session
            if selected.type != "session":
                return  # Only kill sessions, not computers/projects

            # Confirm kill
            curses.endwin()
            print(f"\nKill session: {selected.data.get('title', 'Unknown')}")
            print(f"Computer: {selected.data.get('computer', 'unknown')}")
            print(f"Session ID: {selected.data.get('session_id', 'unknown')}")
            confirm = input("Are you sure? (yes/no): ").strip().lower()
            curses.doupdate()

            if confirm == "yes":
                session_id = str(selected.data.get("session_id", ""))
                computer = str(selected.data.get("computer", ""))

                try:
                    result = asyncio.get_event_loop().run_until_complete(
                        self.api.end_session(session_id=session_id, computer=computer)  # type: ignore[attr-defined]
                    )
                    if result:
                        stdscr.addstr(0, 0, "Session killed. Press [r] to refresh.")  # type: ignore[attr-defined]
                        stdscr.refresh()  # type: ignore[attr-defined]
                        curses.napms(1500)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    stdscr.addstr(0, 0, f"Error killing session: {e}")  # type: ignore[attr-defined]
                    stdscr.refresh()  # type: ignore[attr-defined]
                    curses.napms(2000)

    def render(self, stdscr: object, start_row: int, height: int, width: int) -> None:
        """Render view content.

        Args:
            stdscr: Curses screen object
            start_row: Starting row
            height: Available height
            width: Screen width
        """
        if not self.flat_items:
            msg = "(no items)"
            stdscr.addstr(start_row, 2, msg, curses.A_DIM)  # type: ignore[attr-defined]
            return

        row = start_row
        for i, item in enumerate(self.flat_items):
            if row >= start_row + height:
                break  # No more space

            is_selected = i == self.selected_index
            lines_used = self._render_item(stdscr, row, item, width, is_selected)
            row += lines_used

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
            suffix = f"({session_count} sessions)" if session_count else "(no sessions)"
            line = f"{indent}📁 {path} {suffix}"
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
        except curses.error:
            pass

        # If collapsed, only show line 1
        if is_collapsed:
            return 1

        lines_used = 1

        # Determine which field is "active" (highlight) based on state tracking
        active = self._active_field.get(session_id, "none")
        input_attr = highlight_attr if active == "input" else muted_attr
        output_attr = highlight_attr if active == "output" else muted_attr

        # Calculate content indent (align with agent name)
        # indent + "[X] ▶ " = where agent starts
        content_indent = indent + "      "  # 6 chars for "[X] ▶ "

        # Line 2: Last input (only if content exists)
        last_input = str(session.get("last_input") or "").strip()
        if last_input:
            input_text = last_input.replace("\n", " ")[:60]
            line2 = f"{content_indent}last input: {input_text}"
            try:
                stdscr.addstr(row + lines_used, 0, line2[:width], input_attr)  # type: ignore[attr-defined]
            except curses.error:
                pass
            lines_used += 1

        # Line 3: Last output (only if content exists)
        last_output = str(session.get("last_output") or "").strip()
        if last_output:
            output_text = last_output.replace("\n", " ")[:60]
            line3 = f"{content_indent}last output: {output_text}"
            try:
                stdscr.addstr(row + lines_used, 0, line3[:width], output_attr)  # type: ignore[attr-defined]
            except curses.error:
                pass
            lines_used += 1

        return lines_used
