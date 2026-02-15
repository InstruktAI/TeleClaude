"""Preparation view - shows roadmap and todo-folder discovered work items.

Required reads:
- @docs/project/design/tui-state-layout.md
"""

from __future__ import annotations

import curses
import json
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Callable, Sequence, TypeGuard

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
from teleclaude.cli.tui.controller import TuiController
from teleclaude.cli.tui.pane_manager import ComputerInfo, TmuxPaneManager
from teleclaude.cli.tui.session_launcher import attach_tmux_from_result
from teleclaude.cli.tui.state import DocPreviewState, Intent, IntentType, TuiState
from teleclaude.cli.tui.state_store import save_sticky_state
from teleclaude.cli.tui.theme import (
    get_agent_preview_selected_bg_attr,
    get_agent_preview_selected_focus_attr,
)
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import (
    CursesWindow,
    FocusLevelType,
    NodeType,
    NotificationLevel,
    TodoStatus,
)
from teleclaude.cli.tui.views.base import BaseView, ScrollableViewMixin
from teleclaude.cli.tui.views.interaction import (
    TreeInteractionAction,
    TreeInteractionDecision,
    TreeInteractionState,
)
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
    type: NodeType
    data: PrepComputerDisplayInfo
    depth: int = 0
    children: list["PrepTreeNode"] = field(default_factory=list)


@dataclass
class PrepProjectNode:
    type: NodeType
    data: PrepProjectDisplayInfo
    depth: int = 0
    children: list["PrepTreeNode"] = field(default_factory=list)


@dataclass
class PrepTodoNode:
    type: NodeType
    data: PrepTodoDisplayInfo
    depth: int = 0
    children: list["PrepTreeNode"] = field(default_factory=list)


@dataclass
class PrepFileNode:
    type: NodeType
    data: PrepFileDisplayInfo
    depth: int = 0
    children: list["PrepTreeNode"] = field(default_factory=list)


PrepTreeNode = PrepComputerNode | PrepProjectNode | PrepTodoNode | PrepFileNode


def _is_computer_node(node: PrepTreeNode) -> TypeGuard[PrepComputerNode]:
    return node.type == NodeType.COMPUTER


def _is_project_node(node: PrepTreeNode) -> TypeGuard[PrepProjectNode]:
    return node.type == NodeType.PROJECT


def _is_todo_node(node: PrepTreeNode) -> TypeGuard[PrepTodoNode]:
    return node.type == NodeType.TODO


def _is_file_node(node: PrepTreeNode) -> TypeGuard[PrepFileNode]:
    return node.type == NodeType.FILE


class _PrepInputKind(str, Enum):
    """Normalized preparation interaction kinds."""

    NONE = "none"
    PREVIEW = "preview"
    ACTIVATE = "activate"


@dataclass(frozen=True)
class _PrepInputIntent:
    """Internal preparation interaction intent for a selected file row."""

    item: "PrepFileNode"
    kind: _PrepInputKind
    now: float
    request_focus: bool = False


class PreparationView(ScrollableViewMixin[PrepTreeNode], BaseView):
    """View 2: Preparation - todo-centric tree showing roadmap and folder-based items.

    Shows tree structure: Computer -> Project -> Todos -> Files
    Computers and projects are always expanded.
    Todos can be expanded to show file children discovered from the todo folder.
    Files can be selected for view/edit actions.
    """

    def __init__(
        self,
        api: "TelecAPIClient",
        agent_availability: dict[str, AgentAvailabilityInfo],
        focus: FocusContext,
        pane_manager: TmuxPaneManager,
        state: TuiState,
        controller: TuiController,
        notify: Callable[[str, NotificationLevel], None] | None = None,
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
        self.state = state
        self.controller = controller
        self.notify = notify
        # Tree structure
        self.tree: list[PrepTreeNode] = []
        self.flat_items: list[PrepTreeNode] = []
        # Row-to-item mapping for mouse click handling (built during render)
        self._row_to_item: dict[int, int] = {}
        self._preview_interaction_state = TreeInteractionState()
        self._space_double_press_threshold = 0.65  # seconds
        # Signal for app to trigger data refresh
        self.needs_refresh: bool = False
        # Store computers for SSH connection lookup
        self._computers: list[ApiComputerInfo] = []
        # Visible height for scroll calculations (updated during render)
        self._visible_height: int = 20  # Default, updated in render
        # Track rendered item range for scroll calculations
        self._last_rendered_range: tuple[int, int] = (0, 0)

    @property
    def selected_index(self) -> int:
        return self.state.preparation.selected_index

    @selected_index.setter
    def selected_index(self, value: int) -> None:
        self.state.preparation.selected_index = value

    @property
    def scroll_offset(self) -> int:
        return self.state.preparation.scroll_offset

    @scroll_offset.setter
    def scroll_offset(self, value: int) -> None:
        self.state.preparation.scroll_offset = value

    @property
    def expanded_todos(self) -> set[str]:
        return self.state.preparation.expanded_todos

    @expanded_todos.setter
    def expanded_todos(self, value: set[str]) -> None:
        self.state.preparation.expanded_todos = value

    @property
    def _file_pane_id(self) -> str | None:
        return self.state.preparation.file_pane_id

    @_file_pane_id.setter
    def _file_pane_id(self, value: str | None) -> None:
        self.state.preparation.file_pane_id = value

    @property
    def _preview(self) -> DocPreviewState | None:
        return self.state.preparation.preview

    @_preview.setter
    def _preview(self, value: DocPreviewState | None) -> None:
        self.state.preparation.preview = value

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
        # Key by (computer, path) to avoid cross-computer collisions
        todos_by_project: dict[tuple[str, str], list[TodoItem]] = {}
        todo_ids: set[str] = set()

        for project in projects:
            path = project.path
            computer = project.computer or ""
            if not path:
                continue

            key = (computer, path)
            todos_by_project[key] = [
                TodoItem(
                    slug=todo.slug,
                    status=todo.status,
                    description=todo.description,
                    has_requirements=todo.has_requirements,
                    has_impl_plan=todo.has_impl_plan,
                    build_status=todo.build_status,
                    review_status=todo.review_status,
                    dor_score=todo.dor_score,
                    deferrals_status=todo.deferrals_status,
                    findings_count=todo.findings_count,
                    files=todo.files,
                )
                for todo in project.todos
            ]
            for todo in todos_by_project[key]:
                todo_ids.add(
                    self._todo_node_id(
                        computer=computer,
                        project_path=path,
                        slug=todo.slug,
                    )
                )

        # Aggregate todo and project counts per computer for badges
        todo_counts: dict[str, int] = {}
        project_counts: dict[str, int] = {}
        for project in projects:
            comp_name = project.computer or ""
            if not comp_name or not project.path:
                continue
            project_counts[comp_name] = project_counts.get(comp_name, 0) + 1
            todo_counts[comp_name] = todo_counts.get(comp_name, 0) + len(
                todos_by_project.get((comp_name, project.path), [])
            )

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
        if todo_ids:
            self.controller.dispatch(Intent(IntentType.SYNC_TODOS, {"todo_ids": list(todo_ids)}))

    def _build_tree(
        self,
        computers: list[PrepComputerDisplayInfo],
        projects: list[ProjectWithTodosInfo],
        todos_by_project: dict[tuple[str, str], list[TodoItem]],
    ) -> list[PrepTreeNode]:
        """Build tree structure: Computer -> Project -> Todos.

        Args:
            computers: List of computers
            projects: List of projects
            todos_by_project: Pre-fetched todos keyed by (computer, path)

        Returns:
            Tree of PrepTreeNodes
        """
        tree: list[PrepTreeNode] = []

        for computer in computers:
            comp_name = computer.computer.name
            comp_node = PrepComputerNode(
                type=NodeType.COMPUTER,
                data=computer,
                depth=0,
            )

            # Add projects for this computer
            comp_projects = [p for p in projects if p.computer == comp_name]
            for project in comp_projects:
                project_path = project.path
                proj_node = PrepProjectNode(
                    type=NodeType.PROJECT,
                    data=PrepProjectDisplayInfo(project=project),
                    depth=1,
                )

                # Use pre-fetched todos for this project (keyed by computer+path)
                todos = todos_by_project.get((comp_name, project_path), [])
                for todo in todos:
                    todo_node = PrepTodoNode(
                        type=NodeType.TODO,
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
                if _is_computer_node(node) and node.data.computer.name == self.focus.computer:
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
            if _is_computer_node(node):
                display_node = PrepComputerNode(
                    type=NodeType.COMPUTER,
                    data=node.data,
                    depth=base_depth,
                    children=node.children,
                )
            elif _is_project_node(node):
                display_node = PrepProjectNode(
                    type=NodeType.PROJECT,
                    data=node.data,
                    depth=base_depth,
                    children=node.children,
                )
            elif _is_todo_node(node):
                display_node = PrepTodoNode(
                    type=NodeType.TODO,
                    data=node.data,
                    depth=base_depth,
                    children=node.children,
                )
            else:
                display_node = PrepFileNode(
                    type=NodeType.FILE,
                    data=node.data,
                    depth=base_depth,
                    children=node.children,
                )
            result.append(display_node)

            # Always expand computers and projects
            if _is_computer_node(node) or _is_project_node(node):
                result.extend(self._flatten_tree(node.children, base_depth + 1))
            # Expand todos if in expanded set - add file children
            elif _is_todo_node(node):
                if self._is_todo_expanded(node.data):
                    result.extend(self._create_file_nodes(node, base_depth + 1))

        return result

    def _todo_node_id(self, computer: str, project_path: str, slug: str) -> str:
        """Build a stable identifier for one todo instance."""
        return json.dumps([computer, project_path, slug], separators=(",", ":"))

    def _todo_node_id_from_display(self, todo: PrepTodoDisplayInfo) -> str:
        """Build a stable identifier for a rendered todo row."""
        return self._todo_node_id(todo.computer, todo.project_path, todo.todo.slug)

    @staticmethod
    def _todo_node_id_from_file(item: PrepFileDisplayInfo) -> str:
        """Build a stable identifier for the todo parent of a file row."""
        return json.dumps([item.computer, item.project_path, item.slug], separators=(",", ":"))

    @staticmethod
    def _doc_file_id(item: PrepFileDisplayInfo) -> str:
        """Build a stable absolute identifier for a doc file row."""
        return os.path.join(item.project_path, "todos", item.slug, item.filename)

    def _is_todo_expanded(self, todo: PrepTodoDisplayInfo) -> bool:
        """Return true if todo is expanded; support legacy slug-only IDs."""
        todo_id = self._todo_node_id_from_display(todo)
        return todo_id in self.expanded_todos or todo.todo.slug in self.expanded_todos

    def _is_file_parent_expanded(self, item: PrepFileDisplayInfo) -> bool:
        """Return true if the parent todo for a file node is expanded."""
        file_todo = PrepTodoDisplayInfo(
            todo=TodoItem(
                slug=item.slug,
                status="pending",
                files=[],
                has_requirements=False,
                has_impl_plan=False,
                build_status=None,
                review_status=None,
                dor_score=None,
                deferrals_status=None,
                findings_count=0,
                description=None,
            ),
            project_path=item.project_path,
            computer=item.computer,
        )
        return self._is_todo_expanded(file_todo)

    def _create_file_nodes(self, todo_node: PrepTodoNode, depth: int) -> list[PrepTreeNode]:
        """Create file nodes for an expanded todo.

        Args:
            todo_node: Parent todo node
            depth: Depth for file nodes

        Returns:
            List of file nodes
        """
        file_nodes: list[PrepTreeNode] = []
        todo_info = todo_node.data
        filenames = list(todo_info.todo.files)
        # Backward compatibility while cache refresh catches up.
        if not filenames:
            if todo_info.todo.has_requirements:
                filenames.append("requirements.md")
            if todo_info.todo.has_impl_plan:
                filenames.append("implementation-plan.md")

        for idx, filename in enumerate(filenames, start=1):
            file_node = PrepFileNode(
                type=NodeType.FILE,
                data=PrepFileDisplayInfo(
                    filename=filename,
                    display_name=filename,
                    exists=True,
                    index=idx,
                    slug=todo_info.todo.slug,
                    project_path=todo_info.project_path,
                    computer=todo_info.computer,
                ),
                depth=depth,
            )
            file_nodes.append(file_node)
        return file_nodes

    def _select_index(self, index: int, source: str = "user") -> None:
        """Select row and record selection state via shared controller path."""
        if index == self.selected_index:
            self.selected_index = index
            return
        self.selected_index = index
        self.controller.dispatch(
            Intent(IntentType.SET_SELECTION, {"view": "preparation", "index": index, "source": source})
        )

    @property
    def _space_double_press_threshold(self) -> float:
        """Compatibility alias for interaction state."""
        return self._preview_interaction_state.double_press_threshold

    @_space_double_press_threshold.setter
    def _space_double_press_threshold(self, value: float) -> None:
        self._preview_interaction_state.double_press_threshold = value

    @property
    def _last_space_press_time(self) -> float | None:
        """Compatibility alias for interaction state."""
        return self._preview_interaction_state.last_press_time

    @_last_space_press_time.setter
    def _last_space_press_time(self, value: float | None) -> None:
        self._preview_interaction_state.last_press_time = value

    @property
    def _last_space_file_id(self) -> str | None:
        """Compatibility alias for interaction state."""
        return self._preview_interaction_state.last_press_item_id

    @_last_space_file_id.setter
    def _last_space_file_id(self, value: str | None) -> None:
        self._preview_interaction_state.last_press_item_id = value

    @property
    def _space_double_press_guard_file_id(self) -> str | None:
        """Compatibility alias for interaction state."""
        return self._preview_interaction_state.double_press_guard_item_id

    @_space_double_press_guard_file_id.setter
    def _space_double_press_guard_file_id(self, value: str | None) -> None:
        self._preview_interaction_state.double_press_guard_item_id = value

    @property
    def _space_double_press_guard_until(self) -> float | None:
        """Compatibility alias for interaction state."""
        return self._preview_interaction_state.double_press_guard_until

    @_space_double_press_guard_until.setter
    def _space_double_press_guard_until(self, value: float | None) -> None:
        self._preview_interaction_state.double_press_guard_until = value

    def _build_preview_interaction(
        self,
        selected: PrepFileNode,
        *,
        now: float,
        allow_sticky_toggle: bool,
    ) -> _PrepInputIntent:
        """Build a normalized preview intent for file interactions."""
        file_id = self._doc_file_id(selected.data)
        decision: TreeInteractionDecision = self._preview_interaction_state.decide_preview_action(
            file_id,
            now,
            is_sticky=False,
            allow_sticky_toggle=allow_sticky_toggle,
        )

        if decision.action == TreeInteractionAction.NONE:
            return _PrepInputIntent(selected, _PrepInputKind.NONE, now=now)

        if decision.action == TreeInteractionAction.TOGGLE_STICKY:
            return _PrepInputIntent(
                selected,
                _PrepInputKind.ACTIVATE,
                now=now,
                request_focus=True,
            )

        if decision.action == TreeInteractionAction.CLEAR_STICKY_PREVIEW:
            return _PrepInputIntent(selected, _PrepInputKind.PREVIEW, now=now)

        return _PrepInputIntent(selected, _PrepInputKind.PREVIEW, now=now)

    def _build_click_preview_interaction(self, selected: PrepFileNode, *, now: float) -> _PrepInputIntent:
        """Build single-click preview intent (single preview, no sticky toggle)."""
        return self._build_preview_interaction(selected, now=now, allow_sticky_toggle=False)

    def _build_space_preview_interaction(self, selected: PrepFileNode, *, now: float) -> _PrepInputIntent:
        """Build space-preview intent (single preview, double space activates)."""
        return self._build_preview_interaction(selected, now=now, allow_sticky_toggle=True)

    def _handle_prep_interaction(self, interaction: _PrepInputIntent) -> None:
        """Resolve normalized interaction intent for selected file row."""
        if interaction.kind == _PrepInputKind.NONE:
            return

        selected = interaction.item
        if interaction.kind == _PrepInputKind.ACTIVATE:
            self._open_doc_preview(selected.data, request_focus=True)
            return

        self._open_doc_preview(selected.data, request_focus=interaction.request_focus)

    def get_action_bar(self) -> str:
        """Return action bar string.

        Returns:
            Action bar text
        """
        back_hint = "[<-] Back  " if self.focus.stack else ""

        if not self.flat_items or self.selected_index >= len(self.flat_items):
            return back_hint.strip() if back_hint else ""

        item = self.flat_items[self.selected_index]

        if _is_computer_node(item):
            return f"{back_hint}[->] Focus Computer"
        if _is_project_node(item):
            return f"{back_hint}[Enter] Prepare Project"
        if _is_file_node(item):
            # File actions
            if item.data.exists:
                return f"{back_hint}[Enter] Preview  [c] Close Preview  [e] Edit"
            return f"{back_hint}[e] Create"
        if _is_todo_node(item):
            if item.data.todo.status == TodoStatus.READY:
                return f"{back_hint}[Enter/s] Start  [p] Prepare"
            return f"{back_hint}[p] Prepare"

        return back_hint.strip() if back_hint else ""

    @staticmethod
    def _coerce_todo_status(status: TodoStatus | str) -> TodoStatus | None:
        """Convert todo status value to enum when possible."""
        if isinstance(status, TodoStatus):
            return status
        try:
            return TodoStatus(status)
        except ValueError:
            return None

    @staticmethod
    def _format_enum_value(value: object) -> str:
        """Format enum values for display."""
        if isinstance(value, Enum):
            return str(value.value)
        return str(value)

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
        if _is_file_node(item):
            todo_id = self._todo_node_id_from_file(item.data)
            if todo_id in self.expanded_todos or self._is_file_parent_expanded(item.data):
                self.controller.dispatch(Intent(IntentType.COLLAPSE_TODO, {"todo_id": todo_id}))
                self.rebuild_for_focus()
                save_sticky_state(self.state)
                logger.debug("collapse_selected: collapsed file's parent todo %s", item.data.slug)
                return True
            logger.debug("collapse_selected: file's parent todo not expanded")
            return False

        if _is_todo_node(item):
            todo_id = self._todo_node_id_from_display(item.data)
            slug = item.data.todo.slug
            if self._is_todo_expanded(item.data):
                self.controller.dispatch(Intent(IntentType.COLLAPSE_TODO, {"todo_id": todo_id}))
                self.rebuild_for_focus()
                save_sticky_state(self.state)
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

        if _is_computer_node(item):
            self.focus.push(FocusLevelType.COMPUTER, item.data.computer.name)
            self.rebuild_for_focus()
            self.selected_index = 0
            logger.debug("drill_down: pushed computer focus")
            return True
        if _is_todo_node(item):
            # Expand todo to show file children
            todo_id = self._todo_node_id_from_display(item.data)
            slug = item.data.todo.slug
            if not self._is_todo_expanded(item.data):
                self.controller.dispatch(Intent(IntentType.EXPAND_TODO, {"todo_id": todo_id}))
                self.rebuild_for_focus()
                save_sticky_state(self.state)
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
        todo_ids: list[str] = []
        for item in self.flat_items:
            if _is_todo_node(item):
                todo_ids.append(self._todo_node_id_from_display(item.data))
                count += 1
        self.controller.dispatch(Intent(IntentType.EXPAND_ALL_TODOS, {"todo_ids": todo_ids}))
        logger.debug("expand_all: expanded %d todos, now expanded_todos=%s", count, self.expanded_todos)
        self.rebuild_for_focus()
        save_sticky_state(self.state)

    def collapse_all(self) -> None:
        """Collapse all todos."""
        logger.debug("collapse_all: clearing expanded_todos (was %s)", self.expanded_todos)
        self.controller.dispatch(Intent(IntentType.COLLAPSE_ALL_TODOS))
        self.rebuild_for_focus()
        save_sticky_state(self.state)

    def handle_enter(self, stdscr: CursesWindow) -> None:
        """Handle Enter key.

        Args:
            stdscr: Curses screen object
        """
        item = self._get_selected()
        if not item:
            return

        if _is_computer_node(item):
            self.drill_down()
        elif _is_project_node(item):
            self._prepare_project(item.data, stdscr)
        elif _is_todo_node(item):
            if item.data.todo.status == TodoStatus.READY:
                self._start_work(item.data, stdscr)
            else:
                self.drill_down()
        elif _is_file_node(item):
            # Enter on file = view if exists
            self._handle_prep_file_activation(item, stdscr)

    def _handle_prep_file_activation(self, item: PrepFileNode, stdscr: CursesWindow) -> None:
        """Open a file from preparation with activated/focus semantics."""
        if not item.data.exists:
            return

        if os.environ.get("TMUX"):
            self._handle_prep_interaction(
                _PrepInputIntent(
                    item,
                    _PrepInputKind.ACTIVATE,
                    now=time.perf_counter(),
                    request_focus=True,
                )
            )
            return

        # Preserve current fallback behavior when not running under tmux.
        self._view_file(item.data, stdscr, request_focus=True)

    def _get_selected(self) -> PrepTreeNode | None:
        """Get currently selected item."""
        if 0 <= self.selected_index < len(self.flat_items):
            return self.flat_items[self.selected_index]
        return None

    def _start_work(self, item: PrepTodoDisplayInfo, stdscr: CursesWindow) -> None:
        """Start work on a ready todo via session modal."""
        slug = item.todo.slug
        self._launch_todo_session_modal(
            item,
            default_prompt=f"/next-work {slug}",
            stdscr=stdscr,
        )

    def _prepare(self, item: PrepTodoDisplayInfo, stdscr: CursesWindow) -> None:
        """Prepare a todo via session modal."""
        slug = item.todo.slug
        self._launch_todo_session_modal(
            item,
            default_prompt=f"/next-prepare {slug}",
            stdscr=stdscr,
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

    def _launch_todo_session_modal(
        self,
        item: PrepTodoDisplayInfo,
        default_prompt: str,
        stdscr: CursesWindow,
    ) -> None:
        """Open session modal for todo command and attach selected launch result.

        Args:
            item: Todo context (computer and project path)
            default_prompt: Pre-filled command (e.g. /next-work <slug>)
            stdscr: Curses screen object
        """
        modal = StartSessionModal(
            computer=item.computer,
            project_path=item.project_path,
            api=self.api,
            agent_availability=self.agent_availability,
            default_prompt=default_prompt,
            notify=self.notify,
        )
        result = modal.run(stdscr)
        if result:
            self._attach_new_session(result, item.computer, stdscr)
            self.needs_refresh = True
        elif modal.start_requested:
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
            active_agent = result.agent or ""
            self.pane_manager.show_session(
                tmux_session_name,
                active_agent,
                computer_info=computer_info,
                session_id=result.session_id,
            )
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
        self.controller.dispatch(Intent(IntentType.CLEAR_FILE_PANE_ID))

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
            self.controller.dispatch(Intent(IntentType.SET_FILE_PANE_ID, {"pane_id": result.stdout.strip()}))

    def _build_view_command(self, filepath: str) -> str:
        viewer = "glow -p" if shutil.which("glow") else "less"
        return f"{viewer} {shlex.quote(filepath)}"

    def _open_doc_preview(self, item: PrepFileDisplayInfo, *, request_focus: bool = False) -> None:
        filepath = os.path.join(
            item.project_path,
            "todos",
            item.slug,
            item.filename,
        )
        if not os.environ.get("TMUX"):
            return

        cmd = self._build_view_command(filepath)
        if self._preview and self._preview.doc_id != filepath:
            self.controller.dispatch(Intent(IntentType.CLEAR_PREP_PREVIEW))
        self.controller.dispatch(
            Intent(
                IntentType.SET_PREP_PREVIEW,
                {
                    "doc_id": filepath,
                    "command": cmd,
                    "title": item.display_name,
                },
            )
        )
        if request_focus:
            self.controller.apply_layout(focus=True)

    def _view_file(self, item: PrepFileDisplayInfo, stdscr: CursesWindow, *, request_focus: bool = False) -> None:
        """View a file in glow (or less as fallback) in a tmux split pane.

        Args:
            item: File data dict
            stdscr: Curses screen object for restoration (used when not in tmux)
            request_focus: Whether to focus the doc preview pane
        """
        filepath = os.path.join(
            item.project_path,
            "todos",
            item.slug,
            item.filename,
        )

        # If in tmux, open in preview pane (layout-managed)
        if os.environ.get("TMUX"):
            self._open_doc_preview(item, request_focus=request_focus)
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
        if _is_file_node(item):
            if key == ord(" "):
                if item.data.exists:
                    logger.debug("handle_key: space preview for file")
                    self._handle_prep_interaction(
                        self._build_space_preview_interaction(
                            item,
                            now=time.perf_counter(),
                        )
                    )
                return

            if key == ord("c"):
                self.controller.dispatch(Intent(IntentType.CLEAR_PREP_PREVIEW))
                return
            if key == ord("v") and item.data.exists:
                logger.debug("handle_key: viewing file")
                self._view_file(item.data, stdscr, request_focus=False)
            elif key == ord("e"):
                logger.debug("handle_key: editing file")
                self._edit_file(item.data, stdscr)
            return

        # Todo-specific actions
        if _is_todo_node(item):
            if key == ord("s") and item.data.todo.status == TodoStatus.READY:
                self._start_work(item.data, stdscr)
            elif key == ord("p"):
                self._prepare(item.data, stdscr)

    def handle_click(self, screen_row: int, is_double_click: bool = False) -> bool:
        """Handle mouse click at screen row.

        Args:
            screen_row: The screen row that was clicked
            is_double_click: True if this is a double-click event (unused in this view)

        Returns:
            True if an item was selected, False otherwise
        """
        item_idx = self._row_to_item.get(screen_row)
        if item_idx is not None:
            self._select_index(item_idx)
            item = self.flat_items[item_idx]
            if _is_file_node(item) and item.data.exists:
                if is_double_click:
                    self._handle_prep_interaction(
                        _PrepInputIntent(
                            item,
                            _PrepInputKind.ACTIVATE,
                            now=time.perf_counter(),
                            request_focus=True,
                        )
                    )
                else:
                    self._handle_prep_interaction(
                        self._build_click_preview_interaction(
                            item,
                            now=time.perf_counter(),
                        )
                    )
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

        if _is_computer_node(item):
            name = item.data.computer.name
            project_count = item.data.project_count
            suffix = f"({project_count})" if project_count else ""
            line = f"{indent}🖥  {name} {suffix}"
            return [line[:width]]

        if _is_project_node(item):
            path = item.data.project.path
            todo_count = len(item.children)
            suffix = f"({todo_count})" if todo_count else ""
            line = f"{indent}📁 {path} {suffix}"
            return [line[:width]]

        if _is_todo_node(item):
            return self._format_todo(item, width)

        if _is_file_node(item):
            return self._format_file(item, width, item.data.index)

        return [""]

    def _format_todo(self, item: PrepTodoNode, width: int) -> list[str]:
        """Format a todo item.

        Args:
            item: Todo node
            width: Screen width

        Returns:
            List of formatted lines
        """
        indent = "  " * item.depth
        slug = item.data.todo.slug
        is_expanded = self._is_todo_expanded(item.data)

        # Collapse indicator
        indicator = "v" if is_expanded else ">"

        # Status label (display-friendly)
        status_enum = self._coerce_todo_status(item.data.todo.status)
        status_label = (
            status_enum.display_label if status_enum is not None else self._format_enum_value(item.data.todo.status)
        )

        status_block = self._build_status_block(item.data.todo, status_label)
        line = f"{indent}{indicator} {slug}  [{status_block}]"
        return [line[:width]]

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

    @staticmethod
    def _normalize_phase_value(value: object) -> str:
        if value is None:
            return ""
        return str(value).strip().lower()

    def _is_build_started(self, todo: TodoItem) -> bool:
        build_value = self._normalize_phase_value(todo.build_status)
        return bool(build_value and build_value not in {"pending", "not_started", "-"})

    def _is_review_started(self, todo: TodoItem) -> bool:
        review_value = self._normalize_phase_value(todo.review_status)
        return bool(review_value and review_value not in {"pending", "missing", "not_started", "-"})

    def _is_build_active(self, todo: TodoItem) -> bool:
        build_value = self._normalize_phase_value(todo.build_status)
        if not build_value:
            return False
        # Hide completed/passed build states to reduce clutter.
        return build_value not in {"pending", "not_started", "-", "complete", "completed", "approved", "done", "pass"}

    def _dor_display(self, todo: TodoItem) -> tuple[str, bool]:
        """Return DOR display value and whether it should be highlighted as below threshold."""
        if todo.dor_score is not None:
            return str(todo.dor_score), todo.dor_score < 8
        return "-", False

    def _status_fields(self, todo: TodoItem, roadmap_status: str) -> list[tuple[str, str, bool]]:
        """Return phase-aware status fields as (prefix, value, is_error_value)."""
        fields: list[tuple[str, str, bool]] = [("", roadmap_status, False)]

        review_started = self._is_review_started(todo)
        build_started = self._is_build_started(todo)

        if review_started:
            review_value = self._format_enum_value(todo.review_status) if todo.review_status else "-"
            fields.append(("r:", review_value, False))
            def_value = self._format_enum_value(todo.deferrals_status) if todo.deferrals_status else "-"
            fields.append(("def:", def_value, False))
            findings = str(todo.findings_count) if todo.findings_count >= 0 else "-"
            fields.append(("f:", findings, False))
            return fields

        if self._is_build_active(todo):
            build_value = self._format_enum_value(todo.build_status) if todo.build_status else "-"
            fields.append(("b:", build_value, False))
            return fields

        if not build_started:
            dor_value, _dor_below_expected = self._dor_display(todo)
            fields.append(("dor:", dor_value, False))

        return fields

    def _build_status_block(self, todo: TodoItem, roadmap_status: str) -> str:
        """Build compact, phase-aware status tags for todo rows."""
        return " ".join(f"{prefix}{value}" for prefix, value, _ in self._status_fields(todo, roadmap_status))

    def _status_parts(self, todo: TodoItem, roadmap_status: str) -> list[tuple[str, bool, bool]]:
        """Return render parts as (text, bold, error_color)."""
        parts: list[tuple[str, bool, bool]] = []
        for idx, (prefix, value, is_error_value) in enumerate(self._status_fields(todo, roadmap_status)):
            if idx > 0:
                parts.append((" ", False, False))
            parts.append((prefix, False, False))
            parts.append((value, value != "-", is_error_value and value != "-"))
        return parts

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

        if _is_computer_node(item):
            name = item.data.computer.name
            project_count = item.data.project_count
            suffix = f"({project_count})" if project_count else ""
            line = f"{indent}🖥  {name} {suffix}"
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
            return 1

        if _is_project_node(item):
            path = item.data.project.path
            todo_count = len(item.children)
            suffix = f"({todo_count})" if todo_count else ""
            line = f"{indent}📁 {path} {suffix}"
            # Mute empty projects
            if not todo_count and not selected:
                attr = curses.A_DIM
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
            return 1

        if _is_todo_node(item):
            return self._render_todo(stdscr, row, item, width, selected)

        if _is_file_node(item):
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
            Number of lines used
        """
        indent = "  " * item.depth
        attr = curses.A_REVERSE if selected else 0
        slug = item.data.todo.slug
        is_expanded = self._is_todo_expanded(item.data)

        # Collapse indicator
        indicator = "v" if is_expanded else ">"

        # Status label (display-friendly)
        status_enum = self._coerce_todo_status(item.data.todo.status)
        status_label = (
            status_enum.display_label if status_enum is not None else self._format_enum_value(item.data.todo.status)
        )

        # Determine color for status word
        status_color_pair = 0
        if status_enum == TodoStatus.READY:
            status_color_pair = 25  # green
        elif status_enum == TodoStatus.IN_PROGRESS:
            status_color_pair = 26  # yellow

        status_parts = self._status_parts(item.data.todo, status_label)
        prefix = f"{indent}{indicator} {slug}  ["
        suffix = "]"
        col = 0
        try:
            stdscr.addstr(row, col, prefix[:width], attr)  # type: ignore[attr-defined]
            col += len(prefix)
            remaining = max(0, width - col - len(suffix))
            is_first_value = True
            for part, _is_bold, _is_error in status_parts:
                if remaining <= 0:
                    break
                chunk = part[:remaining]
                part_attr = attr
                # Color only the status word (first non-empty value)
                if is_first_value and part.strip():
                    part_attr |= curses.color_pair(status_color_pair)
                    is_first_value = False
                stdscr.addstr(row, col, chunk, part_attr)  # type: ignore[attr-defined]
                col += len(chunk)
                remaining -= len(chunk)
            if col < width:
                stdscr.addstr(row, col, suffix[: max(0, width - col)], attr)  # type: ignore[attr-defined]
        except curses.error:
            pass

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

        filepath = os.path.join(
            item.project_path,
            "todos",
            item.slug,
            item.filename,
        )
        is_previewed = bool(self._preview and self._preview.doc_id == filepath)

        if is_previewed:
            if selected:
                attr = get_agent_preview_selected_focus_attr("codex")
            else:
                attr = get_agent_preview_selected_bg_attr("codex")
        elif selected:
            attr = get_agent_preview_selected_focus_attr("codex")
        else:
            attr = 0
        if selected and not is_previewed:
            attr |= curses.A_BOLD

        if not exists:
            attr |= curses.A_DIM

        idx_text = f"{index}."
        idx_attr = attr

        try:
            col = 0
            if indent:
                stdscr.addstr(row, col, indent, attr)  # type: ignore[attr-defined]
                col += len(indent)
            stdscr.addstr(row, col, idx_text, idx_attr if not selected else curses.A_REVERSE)  # type: ignore[attr-defined]
            col += len(idx_text)
            remainder = f" {display_name}"
            stdscr.addstr(row, col, remainder[: max(0, width - col)], attr)  # type: ignore[attr-defined]
        except curses.error:
            pass

        return 1
