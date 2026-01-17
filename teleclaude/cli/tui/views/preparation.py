"""Preparation view - shows planned work from todos/roadmap.md."""

from __future__ import annotations

import asyncio
import curses
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal, Sequence

from instrukt_ai_logging import get_logger

from teleclaude.cli.models import (
    AgentAvailabilityInfo,
    CreateSessionResult,
    ProjectWithTodosInfo,
    SessionInfo,
)
from teleclaude.cli.models import (
    ComputerInfo as ApiComputerInfo,
)
from teleclaude.cli.tui.pane_manager import ComputerInfo, TmuxPaneManager
from teleclaude.cli.tui.session_launcher import attach_tmux_from_result
from teleclaude.cli.tui.todos import TodoItem, parse_roadmap
from teleclaude.cli.tui.types import CursesWindow
from teleclaude.cli.tui.views.base import BaseView, ScrollableViewMixin
from teleclaude.cli.tui.widgets.modal import StartSessionModal
from teleclaude.config import config

if TYPE_CHECKING:
    from teleclaude.cli.api_client import TelecAPIClient
    from teleclaude.cli.tui.app import FocusContext

logger = get_logger(__name__)


@dataclass(frozen=True)
class PrepComputerDisplayInfo:
    """Computer info with display counts."""

    computer: ApiComputerInfo
    project_count: int
    todo_count: int


@dataclass(frozen=True)
class PrepProjectDisplayInfo:
    """Project info for preparation view."""

    project: ProjectWithTodosInfo


@dataclass(frozen=True)
class PrepTodoDisplayInfo:
    """Todo info with project context."""

    todo: TodoItem
    project_path: str
    computer: str


@dataclass(frozen=True)
class PrepFileDisplayInfo:
    """File info under a todo."""

    filename: str
    display_name: str
    exists: bool
    index: int
    slug: str
    project_path: str
    computer: str


@dataclass
class PrepComputerNode:
    type: Literal["computer"]
    data: PrepComputerDisplayInfo
    depth: int = 0
    children: list["PrepTreeNode"] = field(default_factory=list)


@dataclass
class PrepProjectNode:
    type: Literal["project"]
    data: PrepProjectDisplayInfo
    depth: int = 0
    children: list["PrepTreeNode"] = field(default_factory=list)


@dataclass
class PrepTodoNode:
    type: Literal["todo"]
    data: PrepTodoDisplayInfo
    depth: int = 0
    children: list["PrepTreeNode"] = field(default_factory=list)


@dataclass
class PrepFileNode:
    type: Literal["file"]
    data: PrepFileDisplayInfo
    depth: int = 0
    children: list["PrepTreeNode"] = field(default_factory=list)


PrepTreeNode = PrepComputerNode | PrepProjectNode | PrepTodoNode | PrepFileNode


class PreparationView(ScrollableViewMixin[PrepTreeNode], BaseView):
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
        api: "TelecAPIClient",
        agent_availability: dict[str, AgentAvailabilityInfo],
        focus: FocusContext,
        pane_manager: TmuxPaneManager,
        notify: Callable[[str, str], None] | None = None,
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
        self.pane_manager = pane_manager
        self.notify = notify
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
        # Signal for app to trigger data refresh
        self.needs_refresh: bool = False
        # Store computers for SSH connection lookup
        self._computers: list[ApiComputerInfo] = []
        # Visible height for scroll calculations (updated during render)
        self._visible_height: int = 20  # Default, updated in render
        # Track rendered item range for scroll calculations
        self._last_rendered_range: tuple[int, int] = (0, 0)

    async def refresh(
        self,
        computers: list[ApiComputerInfo],
        projects: list[ProjectWithTodosInfo],
        sessions: list[SessionInfo],  # noqa: ARG002 - API consistency
    ) -> None:
        """Refresh view data - build tree from computers, projects, todos.

        Args:
            computers: List of computers
            projects: List of projects (with todos included from API)
            sessions: List of sessions (unused)
        """
        logger.debug(
            "PreparationView.refresh: %d computers, %d projects",
            len(computers),
            len(projects),
        )

        # Store computers for SSH connection lookup
        self._computers = computers

        # Extract todos from projects (already fetched by API in one call)
        local_computer = config.computer.name
        todos_by_project: dict[str, list[TodoItem]] = {}

        for project in projects:
            path = project.path
            if not path:
                continue

            # For local projects, parse from filesystem (has state.json with build/review status)
            if project.computer == local_computer:
                todos_by_project[path] = parse_roadmap(path)
            else:
                # For remote projects, use todos from API response
                todos_by_project[path] = [
                    TodoItem(
                        slug=todo.slug,
                        status=todo.status,
                        description=todo.description,
                        has_requirements=todo.has_requirements,
                        has_impl_plan=todo.has_impl_plan,
                        build_status=todo.build_status,
                        review_status=todo.review_status,
                    )
                    for todo in project.todos
                ]

        # Aggregate todo and project counts per computer for badges
        project_by_path: dict[str, str] = {}
        for project in projects:
            if project.computer and project.path:
                project_by_path[project.path] = project.computer

        todo_counts: dict[str, int] = {}
        project_counts: dict[str, int] = {}
        for path, comp_name in project_by_path.items():
            project_counts[comp_name] = project_counts.get(comp_name, 0) + 1
            todo_counts[comp_name] = todo_counts.get(comp_name, 0) + len(todos_by_project.get(path, []))

        enriched_computers: list[PrepComputerDisplayInfo] = []
        for computer in computers:
            name = computer.name
            enriched_computers.append(
                PrepComputerDisplayInfo(
                    computer=computer,
                    project_count=project_counts.get(name, 0),
                    todo_count=todo_counts.get(name, 0),
                )
            )

        self.tree = self._build_tree(enriched_computers, projects, todos_by_project)
        logger.debug("Tree built with %d root nodes", len(self.tree))
        self.rebuild_for_focus()

    def _build_tree(
        self,
        computers: list[PrepComputerDisplayInfo],
        projects: list[ProjectWithTodosInfo],
        todos_by_project: dict[str, list[TodoItem]],
    ) -> list[PrepTreeNode]:
        """Build tree structure: Computer -> Project -> Todos.

        Args:
            computers: List of computers
            projects: List of projects
            todos_by_project: Pre-fetched todos keyed by project path

        Returns:
            Tree of PrepTreeNodes
        """
        tree: list[PrepTreeNode] = []

        for computer in computers:
            comp_name = computer.computer.name
            comp_node = PrepComputerNode(
                type="computer",
                data=computer,
                depth=0,
            )

            # Add projects for this computer
            comp_projects = [p for p in projects if p.computer == comp_name]
            for project in comp_projects:
                project_path = project.path
                proj_node = PrepProjectNode(
                    type="project",
                    data=PrepProjectDisplayInfo(project=project),
                    depth=1,
                )

                # Use pre-fetched todos for this project
                todos = todos_by_project.get(project_path, [])
                for todo in todos:
                    todo_node = PrepTodoNode(
                        type="todo",
                        data=PrepTodoDisplayInfo(
                            todo=todo,
                            project_path=project_path,
                            computer=comp_name,
                        ),
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
                if node.type == "computer" and node.data.computer.name == self.focus.computer:
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

    def _flatten_tree(self, nodes: Sequence[PrepTreeNode], base_depth: int) -> list[PrepTreeNode]:
        """Flatten tree for display.

        Args:
            nodes: Tree nodes
            base_depth: Base depth offset

        Returns:
            Flattened list
        """
        result: list[PrepTreeNode] = []
        for node in nodes:
            display_node: PrepTreeNode
            if node.type == "computer":
                display_node = PrepComputerNode(
                    type="computer",
                    data=node.data,
                    depth=base_depth,
                    children=node.children,
                )
            elif node.type == "project":
                display_node = PrepProjectNode(
                    type="project",
                    data=node.data,
                    depth=base_depth,
                    children=node.children,
                )
            elif node.type == "todo":
                display_node = PrepTodoNode(
                    type="todo",
                    data=node.data,
                    depth=base_depth,
                    children=node.children,
                )
            else:
                display_node = PrepFileNode(
                    type="file",
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
                slug = node.data.todo.slug
                if slug in self.expanded_todos:
                    result.extend(self._create_file_nodes(node, base_depth + 1))

        return result

    def _create_file_nodes(self, todo_node: PrepTodoNode, depth: int) -> list[PrepTreeNode]:
        """Create file nodes for an expanded todo.

        Args:
            todo_node: Parent todo node
            depth: Depth for file nodes

        Returns:
            List of file nodes
        """
        file_nodes: list[PrepTreeNode] = []
        for idx, (filename, display_name, has_flag) in enumerate(self.TODO_FILES, start=1):
            todo_info = todo_node.data
            exists = todo_info.todo.has_requirements if has_flag == "has_requirements" else todo_info.todo.has_impl_plan
            file_node = PrepFileNode(
                type="file",
                data=PrepFileDisplayInfo(
                    filename=filename,
                    display_name=display_name,
                    exists=exists,
                    index=idx,
                    slug=todo_info.todo.slug,
                    project_path=todo_info.project_path,
                    computer=todo_info.computer,
                ),
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
            return f"{back_hint}[Enter] Prepare Project"
        if item.type == "file":
            # File actions
            if item.data.exists:
                return f"{back_hint}[v] View  [e] Edit"
            return f"{back_hint}[e] Create"
        if item.type == "todo":
            if item.data.todo.status == "ready":
                return f"{back_hint}[Enter/s] Start  [p] Prepare"
            return f"{back_hint}[p] Prepare"

        return back_hint.strip() if back_hint else ""

    # move_up() and move_down() inherited from ScrollableViewMixin

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
            slug = item.data.slug
            if slug in self.expanded_todos:
                self.expanded_todos.discard(slug)
                self.rebuild_for_focus()
                logger.debug("collapse_selected: collapsed file's parent todo %s", slug)
                return True
            logger.debug("collapse_selected: file's parent todo not expanded")
            return False

        if item.type == "todo":
            slug = item.data.todo.slug
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
            self.focus.push("computer", item.data.computer.name)
            self.rebuild_for_focus()
            self.selected_index = 0
            logger.debug("drill_down: pushed computer focus")
            return True
        if item.type == "todo":
            # Expand todo to show file children
            slug = item.data.todo.slug
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
                self.expanded_todos.add(item.data.todo.slug)
                count += 1
        logger.debug("expand_all: expanded %d todos, now expanded_todos=%s", count, self.expanded_todos)
        self.rebuild_for_focus()

    def collapse_all(self) -> None:
        """Collapse all todos."""
        logger.debug("collapse_all: clearing expanded_todos (was %s)", self.expanded_todos)
        self.expanded_todos.clear()
        self.rebuild_for_focus()

    def handle_enter(self, stdscr: CursesWindow) -> None:
        """Handle Enter key.

        Args:
            stdscr: Curses screen object
        """
        item = self._get_selected()
        if not item:
            return

        if item.type == "computer":
            self.drill_down()
        elif item.type == "project":
            self._prepare_project(item.data, stdscr)
        elif item.type == "todo":
            if item.data.todo.status == "ready":
                self._start_work(item.data, stdscr)
            else:
                self.drill_down()
        elif item.type == "file":
            # Enter on file = view if exists
            if item.data.exists:
                self._view_file(item.data, stdscr)

    def _get_selected(self) -> PrepTreeNode | None:
        """Get currently selected item."""
        if 0 <= self.selected_index < len(self.flat_items):
            return self.flat_items[self.selected_index]
        return None

    def _start_work(self, item: PrepTodoDisplayInfo, stdscr: CursesWindow) -> None:
        """Start work on a ready todo - launches session in tmux split pane."""
        slug = item.todo.slug
        self._launch_session_split(
            item,
            f"/prime-orchestrator {slug}",
            stdscr,
        )

    def _prepare(self, item: PrepTodoDisplayInfo, stdscr: CursesWindow) -> None:
        """Prepare a todo - launches session in tmux split pane."""
        slug = item.todo.slug
        self._launch_session_split(
            item,
            f"/next-prepare {slug}",
            stdscr,
        )

    def _prepare_project(self, item: PrepProjectDisplayInfo, stdscr: CursesWindow) -> None:
        """Show modal to start a preparation session for a project.

        Args:
            item: Project data dict with computer, path
            stdscr: Curses screen object
        """
        computer = item.project.computer
        project_path = item.project.path

        modal = StartSessionModal(
            computer=computer,
            project_path=project_path,
            api=self.api,
            agent_availability=self.agent_availability,
            default_prompt="/next-prepare",
            notify=self.notify,
        )

        result = modal.run(stdscr)
        if result:
            self._attach_new_session(result, computer, stdscr)
            self.needs_refresh = True
        elif modal.start_requested:
            self.needs_refresh = True

    def _launch_session_split(
        self,
        item: PrepTodoDisplayInfo,
        message: str,
        stdscr: CursesWindow,
    ) -> None:
        """Launch a session and open it in a tmux split pane.

        Args:
            item: Todo data dict with computer, project_path
            message: Initial message/command for the session
            stdscr: Curses screen object for restoration
        """
        # Create the session via API
        result = asyncio.get_event_loop().run_until_complete(
            self.api.create_session(
                computer=item.computer,
                project_path=item.project_path,
                agent="claude",
                thinking_mode="slow",
                message=message,
            )
        )

        computer = item.computer
        self._attach_new_session(result, computer, stdscr)
        self.needs_refresh = True

    def _get_computer_info(self, computer_name: str) -> ComputerInfo | None:
        """Get SSH connection info for a computer."""
        for comp in self._computers:
            if comp.name == computer_name:
                return ComputerInfo(
                    name=computer_name,
                    is_local=comp.is_local,
                    user=comp.user,
                    host=comp.host,
                    tmux_binary=comp.tmux_binary,
                )
        return None

    def _attach_new_session(
        self,
        result: CreateSessionResult,
        computer: str,
        stdscr: CursesWindow,
    ) -> None:
        """Attach newly created session to the side pane immediately."""
        tmux_session_name = result.tmux_session_name or ""
        if not tmux_session_name:
            logger.warning("New session missing tmux_session_name, cannot attach")
            return

        if self.pane_manager.is_available:
            computer_info = self._get_computer_info(computer)
            self.pane_manager.show_session(tmux_session_name, None, computer_info)
        else:
            attach_tmux_from_result(result, stdscr)

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

    def _view_file(self, item: PrepFileDisplayInfo, stdscr: CursesWindow) -> None:
        """View a file in glow (or less as fallback) in a tmux split pane.

        Args:
            item: File data dict
            stdscr: Curses screen object for restoration (used when not in tmux)
        """
        filepath = os.path.join(
            item.project_path,
            "todos",
            item.slug,
            item.filename,
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

    def _edit_file(self, item: PrepFileDisplayInfo, stdscr: CursesWindow) -> None:
        """Edit a file in $EDITOR in a tmux split pane.

        Args:
            item: File data dict
            stdscr: Curses screen object for restoration (used when not in tmux)
        """
        filepath = os.path.join(
            item.project_path,
            "todos",
            item.slug,
            item.filename,
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

    def handle_key(self, key: int, stdscr: CursesWindow) -> None:
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
            if key == ord("v") and item.data.exists:
                logger.debug("handle_key: viewing file")
                self._view_file(item.data, stdscr)
            elif key == ord("e"):
                logger.debug("handle_key: editing file")
                self._edit_file(item.data, stdscr)
            return

        # Todo-specific actions
        if item.type == "todo":
            if key == ord("s") and item.data.todo.status == "ready":
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

    def get_render_lines(self, width: int, height: int) -> list[str]:
        """Return lines this view would render (testable without curses).

        Args:
            width: Tmux width
            height: Tmux height

        Returns:
            List of strings representing what would be rendered
        """
        lines: list[str] = []

        if not self.flat_items:
            lines.append("(no items)")
            return lines

        # Calculate scroll range
        max_scroll = max(0, len(self.flat_items) - height + 3)
        scroll_offset = max(0, min(self.scroll_offset, max_scroll))

        for i, item in enumerate(self.flat_items):
            # Skip items before scroll offset
            if i < scroll_offset:
                continue
            if len(lines) >= height:
                break

            is_selected = i == self.selected_index
            item_lines = self._format_item(item, width, is_selected)
            lines.extend(item_lines)

        return lines

    def _format_item(self, item: PrepTreeNode, width: int, selected: bool) -> list[str]:  # noqa: ARG002
        """Format a single item for display.

        Args:
            item: Tree node
            width: Screen width
            selected: Whether selected (currently unused but kept for consistency)

        Returns:
            List of formatted lines
        """
        indent = "  " * item.depth

        if item.type == "computer":
            name = item.data.computer.name
            project_count = item.data.project_count
            suffix = f"({project_count})" if project_count else ""
            line = f"{indent}🖥  {name} {suffix}"
            return [line[:width]]

        if item.type == "project":
            path = item.data.project.path
            todo_count = len(item.children)
            suffix = f"({todo_count})" if todo_count else ""
            line = f"{indent}📁 {path} {suffix}"
            return [line[:width]]

        if item.type == "todo":
            return self._format_todo(item, width)

        if item.type == "file":
            return self._format_file(item, width, item.data.index)

        return [""]

    def _format_todo(self, item: PrepTodoNode, width: int) -> list[str]:
        """Format a todo item.

        Args:
            item: Todo node
            width: Screen width

        Returns:
            List of formatted lines (1 or 2 depending on state.json)
        """
        indent = "  " * item.depth
        slug = item.data.todo.slug
        is_expanded = slug in self.expanded_todos

        # Collapse indicator
        indicator = "v" if is_expanded else ">"

        # Status marker and label
        marker = self.STATUS_MARKERS.get(item.data.todo.status, "[ ]")
        status_label = item.data.todo.status

        line = f"{indent}{marker} {indicator} {slug}  [{status_label}]"
        lines = [line[:width]]

        # Second line: build/review status (if available)
        build_status = item.data.todo.build_status
        review_status = item.data.todo.review_status
        if build_status or review_status:
            build_str = str(build_status) if build_status else "-"
            review_str = str(review_status) if review_status else "-"
            state_line = f"{indent}      Build: {build_str}  Review: {review_str}"
            lines.append(state_line[:width])

        return lines

    def _format_file(self, item: PrepFileNode, width: int, index: int) -> list[str]:
        """Format a file item.

        Args:
            item: File node
            width: Screen width
            index: File index (1-based for display)

        Returns:
            List of formatted lines
        """
        indent = "  " * item.depth
        display_name = item.data.display_name
        line = f"{indent}{index}. {display_name}"
        return [line[:width]]

    def render(self, stdscr: CursesWindow, start_row: int, height: int, width: int) -> None:
        """Render view content with scrolling support.

        Args:
            stdscr: Curses screen object
            start_row: Starting row
            height: Available height
            width: Screen width
        """
        # Store visible height for scroll calculations
        self._visible_height = height

        # Clear row-to-item mapping (rebuilt each render)
        self._row_to_item.clear()

        if not self.flat_items:
            msg = "(no items)"
            stdscr.addstr(start_row, 2, msg, curses.A_DIM)  # type: ignore[attr-defined]
            return

        # Clamp scroll_offset to valid range
        max_scroll = max(0, len(self.flat_items) - height + 3)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))

        row = start_row
        first_rendered = self.scroll_offset
        last_rendered = self.scroll_offset
        for i, item in enumerate(self.flat_items):
            # Skip items before scroll offset
            if i < self.scroll_offset:
                continue
            if row >= start_row + height:
                break
            last_rendered = i
            is_selected = i == self.selected_index
            lines = self._render_item(stdscr, row, item, width, is_selected)
            # Map all lines of this item to its index (for mouse click)
            for offset in range(lines):
                self._row_to_item[row + offset] = i
            row += lines
        # Track rendered range for scroll calculations
        self._last_rendered_range = (first_rendered, last_rendered)

    def _render_item(
        self,
        stdscr: CursesWindow,
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
            name = item.data.computer.name
            project_count = item.data.project_count
            suffix = f"({project_count})" if project_count else ""
            line = f"{indent}🖥  {name} {suffix}"
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
            return 1

        if item.type == "project":
            path = item.data.project.path
            todo_count = len(item.children)
            suffix = f"({todo_count})" if todo_count else ""
            line = f"{indent}📁 {path} {suffix}"
            # Mute empty projects
            if not todo_count and not selected:
                attr = curses.A_DIM
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
            return 1

        if item.type == "todo":
            return self._render_todo(stdscr, row, item, width, selected)

        if item.type == "file":
            return self._render_file(stdscr, row, item, width, selected, item.data.index)

        return 1

    def _render_todo(
        self,
        stdscr: CursesWindow,
        row: int,
        item: PrepTodoNode,
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
        slug = item.data.todo.slug
        is_expanded = slug in self.expanded_todos

        # Collapse indicator
        indicator = "v" if is_expanded else ">"

        # Status marker and label
        marker = self.STATUS_MARKERS.get(item.data.todo.status, "[ ]")
        status_label = item.data.todo.status

        line = f"{indent}{marker} {indicator} {slug}  [{status_label}]"
        try:
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
        except curses.error:
            pass

        # Second line: build/review status (if available)
        build_status = item.data.todo.build_status
        review_status = item.data.todo.review_status
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
        stdscr: CursesWindow,
        row: int,
        item: PrepFileNode,
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
        display_name = item.data.display_name
        exists = item.data.exists

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
