"""Sessions view - shows running AI sessions."""

import curses

from teleclaude.cli.tui.tree import TreeNode, build_tree
from teleclaude.cli.tui.widgets.modal import StartSessionModal


class SessionsView:
    """View 1: Sessions - project-centric tree with AI-to-AI nesting."""

    def __init__(self, api: object, agent_availability: dict[str, dict[str, object]]):  # guard: loose-dict
        """Initialize sessions view.

        Args:
            api: API client instance
            agent_availability: Agent availability status
        """
        self.api = api
        self.agent_availability = agent_availability
        self.tree: list[TreeNode] = []
        self.flat_items: list[TreeNode] = []
        self.selected_index = 0
        self.scroll_offset = 0

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
        self.tree = build_tree(computers, projects, sessions)
        self.flat_items = self._flatten_tree(self.tree)

    def _flatten_tree(self, nodes: list[TreeNode]) -> list[TreeNode]:
        """Flatten tree for navigation.

        Args:
            nodes: Tree nodes

        Returns:
            Flattened list of nodes
        """
        result: list[TreeNode] = []
        for node in nodes:
            result.append(node)
            result.extend(self._flatten_tree(node.children))
        return result

    def get_action_bar(self) -> str:
        """Return action bar string for this view.

        Returns:
            Action bar text
        """
        return "[Enter] Attach/Start  [k] Kill  [r] Refresh"

    def move_up(self) -> None:
        """Move selection up."""
        self.selected_index = max(0, self.selected_index - 1)

    def move_down(self) -> None:
        """Move selection down."""
        self.selected_index = min(len(self.flat_items) - 1, self.selected_index + 1)

    def handle_enter(self, stdscr: object) -> None:
        """Handle Enter key - attach to session or start new one.

        Args:
            stdscr: Curses screen object
        """
        if not self.flat_items:
            return
        item = self.flat_items[self.selected_index]
        if item.type == "session":
            # Would attach to session here (implementation depends on tmux integration)
            pass
        elif item.type == "project":
            self._start_session_for_project(stdscr, item.data)

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
            # (No automatic refresh to avoid complexity of storing parent app reference)
            pass

    def handle_key(self, key: int, stdscr: object) -> None:
        """Handle view-specific keys.

        Args:
            key: Key code
            stdscr: Curses screen object
        """
        if key == ord("k"):
            # Kill selected session
            if not self.flat_items or self.selected_index >= len(self.flat_items):
                return

            selected = self.flat_items[self.selected_index]
            if selected.type != "session":
                return  # Only kill sessions, not computers/projects

            # Confirm kill
            curses.endwin()  # type: ignore[attr-defined]
            print(f"\nKill session: {selected.data.get('title', 'Unknown')}")
            print(f"Computer: {selected.data.get('computer', 'unknown')}")
            print(f"Session ID: {selected.data.get('session_id', 'unknown')}")
            confirm = input("Are you sure? (yes/no): ").strip().lower()
            curses.doupdate()  # type: ignore[attr-defined]

            if confirm == "yes":
                # Kill the session
                import asyncio  # pylint: disable=import-outside-toplevel

                session_id = str(selected.data.get("session_id", ""))
                computer = str(selected.data.get("computer", ""))

                try:
                    result = asyncio.get_event_loop().run_until_complete(
                        self.api.end_session(session_id=session_id, computer=computer)  # type: ignore[attr-defined]
                    )
                    if result:
                        # Refresh to show updated list
                        stdscr.addstr(0, 0, "Session killed. Press [r] to refresh.")  # type: ignore[attr-defined]
                        stdscr.refresh()  # type: ignore[attr-defined]
                        curses.napms(1500)  # type: ignore[attr-defined]
                except Exception as e:  # pylint: disable=broad-exception-caught
                    stdscr.addstr(0, 0, f"Error killing session: {e}")  # type: ignore[attr-defined]
                    stdscr.refresh()  # type: ignore[attr-defined]
                    curses.napms(2000)  # type: ignore[attr-defined]

    def render(self, stdscr: object, start_row: int, height: int, width: int) -> None:
        """Render view content.

        Args:
            stdscr: Curses screen object
            start_row: Starting row
            height: Available height
            width: Screen width
        """
        visible_start = self.scroll_offset
        visible_end = min(len(self.flat_items), visible_start + height)

        for i, item in enumerate(self.flat_items[visible_start:visible_end]):
            row = start_row + i
            is_selected = (visible_start + i) == self.selected_index
            self._render_item(stdscr, row, item, width, is_selected)

    def _render_item(self, stdscr: object, row: int, item: TreeNode, width: int, selected: bool) -> None:
        """Render a single tree item.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            item: Tree node
            width: Screen width
            selected: Whether this item is selected
        """
        indent = "  " * item.depth
        attr = curses.A_REVERSE if selected else 0

        if item.type == "computer":
            line = f"{indent}{item.data.get('name', ''): <50} online"
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
        elif item.type == "project":
            path = str(item.data.get("path", ""))
            sessions_text = "(no sessions)" if not item.children else ""
            line = f"{indent}{path} {sessions_text}"
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
        elif item.type == "session":
            self._render_session(stdscr, row, item, width, selected)

    def _render_session(self, stdscr: object, row: int, item: TreeNode, width: int, selected: bool) -> None:
        """Render session with input/output lines.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            item: Session node
            width: Screen width
            selected: Whether this item is selected
        """
        session = item.data
        indent = "  " * item.depth
        agent = str(session.get("active_agent", "?"))
        mode = str(session.get("thinking_mode", "?"))
        title = str(session.get("title", "Untitled"))[:30]
        idx = str(session.get("display_index", "?"))
        attr = curses.A_REVERSE if selected else 0

        # Line 1: Identifier
        line1 = f'{indent}[{idx}] {agent}/{mode}  "{title}"'
        stdscr.addstr(row, 0, line1[:width], attr)  # type: ignore[attr-defined]

        # Lines 2-3: Input/Output would be rendered with color pairs
        # (Simplified here - full implementation uses curses.color_pair)
