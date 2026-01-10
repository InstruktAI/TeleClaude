"""Preparation view - shows planned work from todos/roadmap.md."""

from __future__ import annotations

import asyncio
import curses
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui.todos import parse_roadmap
from teleclaude.config import config

if TYPE_CHECKING:
    from teleclaude.cli.tui.app import FocusContext

logger = get_logger(__name__)


@dataclass
class PrepTreeNode:
    """A node in the preparation tree."""

    type: str  # "computer", "project", "todo", "file"
    data: dict[str, object]  # guard: loose-dict
    depth: int = 0
    children: list[PrepTreeNode] = field(default_factory=list)


class PreparationView:
    """View 2: Preparation - todo-centric tree showing roadmap items.

    Shows tree structure: Computer -> Project -> Todos -> Files
    Computers and projects are always expanded.
    Todos can be expanded to show file children (requirements.md, implementation-plan.md).
    Files can be selected for view/edit actions.
    """

    STATUS_MARKERS: dict[str, str] = {
        "pending": "[ ]",
        "ready": "[.]",
        "in_progress": "[>]",
    }

    # Known files in todo folders
    TODO_FILES = [
        ("requirements.md", "Requirements", "has_requirements"),
        ("implementation-plan.md", "Implementation Plan", "has_impl_plan"),
    ]

    def __init__(
        self,
        api: object,
        agent_availability: dict[str, dict[str, object]],  # guard: loose-dict
        focus: FocusContext,
    ):
        """Initialize preparation view.

        Args:
            api: API client instance
            agent_availability: Agent availability status
            focus: Shared focus context
        """
        self.api = api
        self.agent_availability = agent_availability
        self.focus = focus
        # Tree structure
        self.tree: list[PrepTreeNode] = []
        self.flat_items: list[PrepTreeNode] = []
        self.selected_index = 0
        self.scroll_offset = 0
        # Expanded todos (show file children)
        self.expanded_todos: set[str] = set()
        # Track file viewer/editor pane (only one at a time)
        self._file_pane_id: str | None = None
        # Row-to-item mapping for mouse click handling (built during render)
        self._row_to_item: dict[int, int] = {}

    async def refresh(
        self,
        computers: list[dict[str, object]],  # guard: loose-dict
        projects: list[dict[str, object]],  # guard: loose-dict
        sessions: list[dict[str, object]],  # noqa: ARG002 - API consistency  # guard: loose-dict
    ) -> None:
        """Refresh view data - build tree from computers, projects, todos.

        Args:
            computers: List of computers
            projects: List of projects
            sessions: List of sessions (unused)
        """
        logger.debug(
            "PreparationView.refresh: %d computers, %d projects",
            len(computers),
            len(projects),
        )
        self.tree = self._build_tree(computers, projects)
        logger.debug("Tree built with %d root nodes", len(self.tree))
        self.rebuild_for_focus()

    def _build_tree(
        self,
        computers: list[dict[str, object]],  # guard: loose-dict
        projects: list[dict[str, object]],  # guard: loose-dict
    ) -> list[PrepTreeNode]:
        """Build tree structure: Computer -> Project -> Todos.

        Args:
            computers: List of computers
            projects: List of projects

        Returns:
            Tree of PrepTreeNodes
        """
        tree: list[PrepTreeNode] = []

        for computer in computers:
            comp_name = str(computer.get("name", ""))
            comp_node = PrepTreeNode(
                type="computer",
                data={"name": comp_name, "status": computer.get("status", "online")},
                depth=0,
            )

            # Add projects for this computer
            comp_projects = [p for p in projects if p.get("computer") == comp_name]
            for project in comp_projects:
                project_path = str(project.get("path", ""))
                proj_node = PrepTreeNode(
                    type="project",
                    data={"path": project_path, "computer": comp_name},
                    depth=1,
                )

                # Parse todos for this project
                todos = parse_roadmap(project_path)
                for todo in todos:
                    todo_node = PrepTreeNode(
                        type="todo",
                        data={
                            "slug": todo.slug,
                            "status": todo.status,
                            "has_requirements": todo.has_requirements,
                            "has_impl_plan": todo.has_impl_plan,
                            "build_status": todo.build_status,
                            "review_status": todo.review_status,
                            "project_path": project_path,
                            "computer": comp_name,
                        },
                        depth=2,
                    )
                    proj_node.children.append(todo_node)

                comp_node.children.append(proj_node)

            tree.append(comp_node)

        return tree

    def rebuild_for_focus(self) -> None:
        """Rebuild flat_items based on current focus context."""
        logger.debug(
            "PreparationView.rebuild_for_focus: focus.computer=%s, expanded_todos=%s",
            self.focus.computer,
            self.expanded_todos,
        )
        nodes = self.tree

        # Filter by focused computer
        if self.focus.computer:
            for node in self.tree:
                if node.type == "computer" and node.data.get("name") == self.focus.computer:
                    nodes = [node]
                    logger.debug("Filtered to computer '%s'", self.focus.computer)
                    break
            else:
                nodes = []
                logger.warning("Computer '%s' not found in tree", self.focus.computer)

        # Flatten tree (computers and projects always expanded)
        self.flat_items = self._flatten_tree(nodes, base_depth=0)
        logger.debug("Flattened to %d items", len(self.flat_items))

        # Reset selection if out of bounds
        if self.selected_index >= len(self.flat_items):
            self.selected_index = max(0, len(self.flat_items) - 1)
        self.scroll_offset = 0

    def _flatten_tree(self, nodes: list[PrepTreeNode], base_depth: int) -> list[PrepTreeNode]:
        """Flatten tree for display.

        Args:
            nodes: Tree nodes
            base_depth: Base depth offset

        Returns:
            Flattened list
        """
        result: list[PrepTreeNode] = []
        for node in nodes:
            display_node = PrepTreeNode(
                type=node.type,
                data=node.data,
                depth=base_depth,
                children=node.children,
            )
            result.append(display_node)

            # Always expand computers and projects
            if node.type in ("computer", "project"):
                result.extend(self._flatten_tree(node.children, base_depth + 1))
            # Expand todos if in expanded set - add file children
            elif node.type == "todo":
                slug = str(node.data.get("slug", ""))
                if slug in self.expanded_todos:
                    result.extend(self._create_file_nodes(node, base_depth + 1))

        return result

    def _create_file_nodes(self, todo_node: PrepTreeNode, depth: int) -> list[PrepTreeNode]:
        """Create file nodes for an expanded todo.

        Args:
            todo_node: Parent todo node
            depth: Depth for file nodes

        Returns:
            List of file nodes
        """
        file_nodes: list[PrepTreeNode] = []
        for idx, (filename, display_name, has_flag) in enumerate(self.TODO_FILES, start=1):
            exists = bool(todo_node.data.get(has_flag, False))
            file_node = PrepTreeNode(
                type="file",
                data={
                    "filename": filename,
                    "display_name": display_name,
                    "exists": exists,
                    "index": idx,
                    "slug": todo_node.data.get("slug"),
                    "project_path": todo_node.data.get("project_path"),
                    "computer": todo_node.data.get("computer"),
                },
                depth=depth,
            )
            file_nodes.append(file_node)
        return file_nodes

    def get_action_bar(self) -> str:
        """Return action bar string.

        Returns:
            Action bar text
        """
        back_hint = "[<-] Back  " if self.focus.stack else ""

        if not self.flat_items or self.selected_index >= len(self.flat_items):
            return back_hint.strip() if back_hint else ""

        item = self.flat_items[self.selected_index]

        if item.type == "computer":
            return f"{back_hint}[->] Focus Computer"
        if item.type == "project":
            return back_hint.strip() if back_hint else ""
        if item.type == "file":
            # File actions
            if item.data.get("exists"):
                return f"{back_hint}[v] View  [e] Edit"
            return f"{back_hint}[e] Create"
        # Todo actions
        if item.data.get("status") == "ready":
            return f"{back_hint}[Enter/s] Start  [p] Prepare"
        return f"{back_hint}[p] Prepare"

    def move_up(self) -> None:
        """Move selection up."""
        self.selected_index = max(0, self.selected_index - 1)

    def move_down(self) -> None:
        """Move selection down."""
        self.selected_index = min(len(self.flat_items) - 1, self.selected_index + 1)

    def collapse_selected(self) -> bool:
        """Collapse selected todo or navigate to parent.

        Returns:
            True if collapsed, False otherwise
        """
        if not self.flat_items or self.selected_index >= len(self.flat_items):
            logger.debug("collapse_selected: no items or invalid index")
            return False

        item = self.flat_items[self.selected_index]
        logger.debug("collapse_selected: item.type=%s", item.type)

        # If on a file, collapse parent todo
        if item.type == "file":
            slug = str(item.data.get("slug", ""))
            if slug in self.expanded_todos:
                self.expanded_todos.discard(slug)
                self.rebuild_for_focus()
                logger.debug("collapse_selected: collapsed file's parent todo %s", slug)
                return True
            logger.debug("collapse_selected: file's parent todo not expanded")
            return False

        if item.type == "todo":
            slug = str(item.data.get("slug", ""))
            if slug in self.expanded_todos:
                self.expanded_todos.discard(slug)
                self.rebuild_for_focus()
                logger.debug("collapse_selected: collapsed todo %s", slug)
                return True
            logger.debug("collapse_selected: todo already collapsed")
            return False  # Already collapsed

        logger.debug("collapse_selected: not a collapsible item type")
        return False

    def drill_down(self) -> bool:
        """Drill down / expand selected item.

        Returns:
            True if action taken, False otherwise
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
        if item.type == "todo":
            # Expand todo to show file children
            slug = str(item.data.get("slug", ""))
            if slug not in self.expanded_todos:
                self.expanded_todos.add(slug)
                self.rebuild_for_focus()
                logger.debug("drill_down: expanded todo %s", slug)
                return True
            logger.debug("drill_down: todo already expanded")
            return False  # Already expanded
        logger.debug("drill_down: no action for type=%s", item.type)
        return False

    def expand_all(self) -> None:
        """Expand all todos."""
        logger.debug("expand_all: expanding all todos (currently %d items)", len(self.flat_items))
        count = 0
        for item in self.flat_items:
            if item.type == "todo":
                self.expanded_todos.add(str(item.data.get("slug", "")))
                count += 1
        logger.debug("expand_all: expanded %d todos, now expanded_todos=%s", count, self.expanded_todos)
        self.rebuild_for_focus()

    def collapse_all(self) -> None:
        """Collapse all todos."""
        logger.debug("collapse_all: clearing expanded_todos (was %s)", self.expanded_todos)
        self.expanded_todos.clear()
        self.rebuild_for_focus()

    def handle_enter(self, stdscr: object) -> None:
        """Handle Enter key.

        Args:
            stdscr: Curses screen object
        """
        item = self._get_selected()
        if not item:
            return

        if item.type == "computer":
            self.drill_down()
        elif item.type == "todo":
            if item.data.get("status") == "ready":
                self._start_work(item.data, stdscr)
            else:
                self.drill_down()
        elif item.type == "file":
            # Enter on file = view if exists
            if item.data.get("exists"):
                self._view_file(item.data, stdscr)

    def _get_selected(self) -> PrepTreeNode | None:
        """Get currently selected item."""
        if 0 <= self.selected_index < len(self.flat_items):
            return self.flat_items[self.selected_index]
        return None

    def _start_work(self, item: dict[str, object], stdscr: object) -> None:  # guard: loose-dict
        """Start work on a ready todo - launches session in tmux split pane."""
        slug = str(item.get("slug", ""))
        self._launch_session_split(
            item,
            f"/prime-orchestrator {slug}",
            stdscr,
        )

    def _prepare(self, item: dict[str, object], stdscr: object) -> None:  # guard: loose-dict
        """Prepare a todo - launches session in tmux split pane."""
        slug = str(item.get("slug", ""))
        self._launch_session_split(
            item,
            f"/next-prepare {slug}",
            stdscr,
        )

    def _launch_session_split(
        self,
        item: dict[str, object],  # guard: loose-dict
        message: str,
        stdscr: object,
    ) -> None:
        """Launch a session and open it in a tmux split pane.

        Args:
            item: Todo data dict with computer, project_path
            message: Initial message/command for the session
            stdscr: Curses screen object for restoration
        """
        # Create the session via API
        result = asyncio.get_event_loop().run_until_complete(
            self.api.create_session(  # type: ignore[attr-defined]
                computer=item.get("computer"),
                project_dir=item.get("project_path"),
                agent="claude",
                thinking_mode="slow",
                message=message,
            )
        )

        tmux_session_name = result.get("tmux_session_name")
        if not tmux_session_name:
            return

        # Check if we're inside tmux
        in_tmux = bool(os.environ.get("TMUX"))
        if not in_tmux:
            return

        # Save curses state and exit
        curses.def_prog_mode()
        curses.endwin()

        # Split window horizontally and attach to the new session
        tmux = config.computer.tmux_binary
        subprocess.run(
            [tmux, "split-window", "-h", "-p", "60", f"{tmux} attach -t {tmux_session_name}"],
            check=False,
        )

        # Restore curses state
        curses.reset_prog_mode()
        stdscr.refresh()  # type: ignore[attr-defined]

    def _close_file_pane(self) -> None:
        """Close existing file viewer/editor pane if one exists."""
        if not self._file_pane_id:
            return
        tmux = config.computer.tmux_binary
        # Check if pane still exists before trying to kill it
        result = subprocess.run(
            [tmux, "list-panes", "-F", "#{pane_id}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if self._file_pane_id in result.stdout.split("\n"):
            subprocess.run([tmux, "kill-pane", "-t", self._file_pane_id], check=False)
        self._file_pane_id = None

    def _open_file_pane(self, cmd: str) -> None:
        """Open a file in a tmux split pane, closing any existing file pane first.

        Args:
            cmd: Shell command to run (e.g., "glow -p /path/to/file")
        """
        tmux = config.computer.tmux_binary
        # Close existing file pane first
        self._close_file_pane()
        # Open new pane and capture its ID
        result = subprocess.run(
            [tmux, "split-window", "-h", "-p", "60", "-P", "-F", "#{pane_id}", cmd],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip():
            self._file_pane_id = result.stdout.strip()

    def _view_file(self, item: dict[str, object], stdscr: object) -> None:  # guard: loose-dict
        """View a file in glow (or less as fallback) in a tmux split pane.

        Args:
            item: File data dict
            stdscr: Curses screen object for restoration (used when not in tmux)
        """
        filepath = os.path.join(
            str(item.get("project_path", "")),
            "todos",
            str(item.get("slug", "")),
            str(item.get("filename", "")),
        )

        # If in tmux, open in split pane (closes existing file pane first)
        if os.environ.get("TMUX"):
            viewer = "glow -p" if shutil.which("glow") else "less"
            cmd = f"{viewer} {shlex.quote(filepath)}"
            self._open_file_pane(cmd)
            return

        # Fallback: take over terminal if not in tmux
        curses.def_prog_mode()
        curses.endwin()
        try:
            subprocess.run(["glow", "-p", filepath], check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            subprocess.run(["less", filepath], check=False)
        curses.reset_prog_mode()
        stdscr.refresh()  # type: ignore[attr-defined]

    def _edit_file(self, item: dict[str, object], stdscr: object) -> None:  # guard: loose-dict
        """Edit a file in $EDITOR in a tmux split pane.

        Args:
            item: File data dict
            stdscr: Curses screen object for restoration (used when not in tmux)
        """
        filepath = os.path.join(
            str(item.get("project_path", "")),
            "todos",
            str(item.get("slug", "")),
            str(item.get("filename", "")),
        )
        editor = os.environ.get("EDITOR", "vim")

        # If in tmux, open in split pane (closes existing file pane first)
        if os.environ.get("TMUX"):
            cmd = f"{editor} {shlex.quote(filepath)}"
            self._open_file_pane(cmd)
            return

        # Fallback: take over terminal if not in tmux
        curses.def_prog_mode()
        curses.endwin()
        subprocess.run([editor, filepath], check=False)
        # Restore curses state
        curses.reset_prog_mode()
        stdscr.refresh()  # type: ignore[attr-defined]

    def handle_key(self, key: int, stdscr: object) -> None:
        """Handle view-specific keys.

        Args:
            key: Key code
            stdscr: Curses screen object
        """
        key_char = chr(key) if 32 <= key < 127 else f"({key})"
        logger.debug("PreparationView.handle_key: key=%s (%d)", key_char, key)

        # Global expand/collapse
        if key == ord("+") or key == ord("="):
            logger.debug("handle_key: expand_all triggered")
            self.expand_all()
            return
        if key == ord("-"):
            logger.debug("handle_key: collapse_all triggered")
            self.collapse_all()
            return

        item = self._get_selected()
        if not item:
            logger.debug("handle_key: no item selected, ignoring key")
            return

        logger.debug("handle_key: selected item.type=%s", item.type)

        # File-specific actions
        if item.type == "file":
            if key == ord("v") and item.data.get("exists"):
                logger.debug("handle_key: viewing file")
                self._view_file(item.data, stdscr)
            elif key == ord("e"):
                logger.debug("handle_key: editing file")
                self._edit_file(item.data, stdscr)
            return

        # Todo-specific actions
        if item.type == "todo":
            if key == ord("s") and item.data.get("status") == "ready":
                self._start_work(item.data, stdscr)
            elif key == ord("p"):
                self._prepare(item.data, stdscr)

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
        """Render view content.

        Args:
            stdscr: Curses screen object
            start_row: Starting row
            height: Available height
            width: Screen width
        """
        # Clear row-to-item mapping (rebuilt each render)
        self._row_to_item.clear()

        if not self.flat_items:
            msg = "(no items)"
            stdscr.addstr(start_row, 2, msg, curses.A_DIM)  # type: ignore[attr-defined]
            return

        row = start_row
        for i, item in enumerate(self.flat_items):
            if row >= start_row + height:
                break
            is_selected = i == self.selected_index
            lines = self._render_item(stdscr, row, item, width, is_selected)
            # Map all lines of this item to its index (for mouse click)
            for offset in range(lines):
                self._row_to_item[row + offset] = i
            row += lines

    def _render_item(
        self,
        stdscr: object,
        row: int,
        item: PrepTreeNode,
        width: int,
        selected: bool,
    ) -> int:
        """Render a single item.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            item: Tree node
            width: Screen width
            selected: Whether selected

        Returns:
            Number of lines used
        """
        indent = "  " * item.depth
        attr = curses.A_REVERSE if selected else 0

        if item.type == "computer":
            name = str(item.data.get("name", ""))
            line = f"{indent}[C] {name}"
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
            return 1

        if item.type == "project":
            path = str(item.data.get("path", ""))
            todo_count = len(item.children)
            suffix = f"({todo_count})" if todo_count else ""
            line = f"{indent}[P] {path} {suffix}"
            # Mute empty projects
            if not todo_count and not selected:
                attr = curses.A_DIM
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
            return 1

        if item.type == "todo":
            return self._render_todo(stdscr, row, item, width, selected)

        if item.type == "file":
            file_index = item.data.get("index", 1)
            return self._render_file(stdscr, row, item, width, selected, int(str(file_index)))

        return 1

    def _render_todo(
        self,
        stdscr: object,
        row: int,
        item: PrepTreeNode,
        width: int,
        selected: bool,
    ) -> int:
        """Render a todo item.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            item: Todo node
            width: Screen width
            selected: Whether selected

        Returns:
            Number of lines used (1 or 2 depending on state.json existence)
        """
        indent = "  " * item.depth
        attr = curses.A_REVERSE if selected else 0
        slug = str(item.data.get("slug", ""))
        is_expanded = slug in self.expanded_todos

        # Collapse indicator
        indicator = "v" if is_expanded else ">"

        # Status marker and label
        marker = self.STATUS_MARKERS.get(str(item.data.get("status", "pending")), "[ ]")
        status_label = str(item.data.get("status", "pending"))

        line = f"{indent}{marker} {indicator} {slug}  [{status_label}]"
        try:
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
        except curses.error:
            pass

        # Second line: build/review status (if available)
        build_status = item.data.get("build_status")
        review_status = item.data.get("review_status")
        if build_status or review_status:
            build_str = str(build_status) if build_status else "-"
            review_str = str(review_status) if review_status else "-"
            state_line = f"{indent}      Build: {build_str}  Review: {review_str}"
            try:
                stdscr.addstr(row + 1, 0, state_line[:width], curses.A_DIM)  # type: ignore[attr-defined]
            except curses.error:
                pass
            return 2

        return 1

    def _render_file(
        self,
        stdscr: object,
        row: int,
        item: PrepTreeNode,
        width: int,
        selected: bool,
        index: int,
    ) -> int:
        """Render a file item.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            item: File node
            width: Screen width
            selected: Whether selected
            index: File index (1-based for display)

        Returns:
            Number of lines used
        """
        indent = "  " * item.depth
        display_name = str(item.data.get("display_name", ""))
        exists = bool(item.data.get("exists", False))

        # Dimmed if file doesn't exist, normal otherwise
        if selected:
            attr = curses.A_REVERSE
        elif not exists:
            attr = curses.A_DIM
        else:
            attr = 0

        line = f"{indent}{index}. {display_name}"
        try:
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
        except curses.error:
            pass

        return 1
