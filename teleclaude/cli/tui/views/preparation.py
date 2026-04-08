"""Preparation view with todo tree display."""

from __future__ import annotations

import shlex
import sys
import time as _t

from instrukt_ai_logging import get_logger
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.api_models import AgentAvailabilityDTO, ComputerDTO, ProjectDTO, ProjectWithTodosDTO
from teleclaude.cli.tui.messages import (
    CreateSessionRequest,
    StateChanged,
)
from teleclaude.cli.tui.prep_tree import build_dep_tree
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.tree import ComputerDisplayInfo
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.views.preparation_actions import PreparationViewActionsMixin
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.group_separator import GroupSeparator
from teleclaude.cli.tui.widgets.icebox_separator import IceboxSeparator
from teleclaude.cli.tui.widgets.modals import StartSessionModal
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
from teleclaude.cli.tui.widgets.todo_row import TodoRow
from teleclaude.todo_artifacts import artifact_display_filename


class PreparationView(PreparationViewActionsMixin, Widget, can_focus=True):  # pylint: disable=too-many-instance-attributes
    """Preparation tab view showing todo items grouped by project.

    Navigation: arrows, left/right expand/collapse, Enter = toggle expand,
    =/- expand/collapse all, p = prepare, s = start work.
    """

    DEFAULT_CSS = """
    PreparationView {
        width: 100%;
        height: 100%;
    }
    PreparationView VerticalScroll {
        width: 100%;
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up", key_display="↑", group=Binding.Group("Nav", compact=True), show=False),
        Binding("down", "cursor_down", "Down", key_display="↓", group=Binding.Group("Nav", compact=True), show=False),
        Binding("left", "collapse", "Collapse", key_display="←", group=Binding.Group("Fold", compact=True), show=False),
        Binding("right", "expand", "Expand", key_display="→", group=Binding.Group("Fold", compact=True), show=False),
        Binding("enter", "activate", "Toggle/Edit", show=False),
        Binding("space", "preview_file", "View"),
        Binding(
            "equals_sign", "expand_all", "All", key_display="+", group=Binding.Group("Fold", compact=True), show=False
        ),
        Binding(
            "minus", "collapse_all", "None", key_display="-", group=Binding.Group("Fold", compact=True), show=False
        ),
        Binding("n", "new_todo", "Todo"),
        Binding("n", "new_project", "New Project"),
        Binding("b", "new_bug", "Bug"),
        Binding("p", "prepare", "Prep"),
        Binding("s", "start_work", "Start"),
        Binding("r", "refine", "Refine"),
        Binding("R", "remove_todo", "Remove"),
        Binding("f", "freeze", "Freeze"),
        Binding("i", "toggle_icebox", "Icebox"),
        Binding("u", "unfreeze", "Unfreeze"),
        Binding("shift+up", "move_todo_up", "Move Up", key_display="Shift+↑"),
        Binding("shift+down", "move_todo_down", "Move Down", key_display="Shift+↓"),
    ]

    cursor_index = reactive(0)
    persistence_key = "preparation"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._projects_with_todos: list[ProjectWithTodosDTO] = []
        self._expanded_todos: set[str] = set()
        self._icebox_projects: set[str] = set()
        self._nav_items: list[Widget] = []
        self._slug_to_project_path: dict[str, str] = {}
        self._slug_to_computer: dict[str, str] = {}
        self._availability: dict[str, AgentAvailabilityDTO] = {}

    def compose(self) -> ComposeResult:
        scroll = VerticalScroll(id="preparation-scroll")
        scroll.can_focus = False
        yield scroll

    _logger = get_logger(__name__)

    @staticmethod
    def _todo_fingerprint(projects: list[ProjectWithTodosDTO]) -> tuple[tuple[str, ...], ...]:
        """Build a lightweight fingerprint of all todo data for change detection."""
        return tuple(
            (
                t.slug,
                t.status,
                str(t.dor_score),
                t.build_status or "",
                t.review_status or "",
                t.deferrals_status or "",
                str(t.findings_count),
                str(t.has_requirements),
                str(t.has_impl_plan),
                ",".join(t.files),
                ",".join(t.after),
                t.group or "",
                getattr(t, "prepare_phase", None) or "",
                getattr(t, "integration_phase", None) or "",
                getattr(t, "finalize_status", None) or "",
            )
            for p in projects
            for t in (p.todos or [])
        )

    def update_data(
        self,
        projects_with_todos: list[ProjectWithTodosDTO],
        availability: dict[str, AgentAvailabilityDTO] | None = None,
    ) -> None:
        """Update view with fresh API data. Only rebuild if data changed."""
        self._logger.trace(
            "[PERF] PrepView.update_data called items=%d t=%.3f", len(projects_with_todos), _t.monotonic()
        )
        if availability is not None:
            self._availability = availability
        old_fp = self._todo_fingerprint(self._projects_with_todos)
        new_fp = self._todo_fingerprint(projects_with_todos)
        self._projects_with_todos = projects_with_todos
        if old_fp != new_fp or not self._nav_items:
            self._rebuild()

    def set_availability(self, availability: dict[str, AgentAvailabilityDTO]) -> None:
        """Update cached agent availability without rebuilding the view."""
        self._availability = availability

    def load_persisted_state(self, data: dict[str, object]) -> None:  # guard: loose-dict
        """Restore persisted expanded and icebox state."""
        expanded_todos = data.get("expanded_todos", [])
        if isinstance(expanded_todos, list):
            self._expanded_todos = {str(item) for item in expanded_todos}
        icebox_projects = data.get("icebox_projects", [])
        if isinstance(icebox_projects, list):
            self._icebox_projects = {str(item) for item in icebox_projects}

    def _rebuild(self) -> None:  # noqa: C901  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        """Rebuild the todo display from current data (Computer → Project → Todo)."""
        _rb0 = _t.monotonic()
        self._logger.trace("[PERF] PrepView._rebuild START t=%.3f", _rb0)
        container = self.query_one("#preparation-scroll", VerticalScroll)
        container.remove_children()
        self._nav_items.clear()

        # Build slug -> project path and slug -> computer mappings
        self._slug_to_project_path.clear()
        self._slug_to_computer.clear()
        for p in self._projects_with_todos:
            for t in p.todos or []:
                self._slug_to_project_path[t.slug] = p.path
                self._slug_to_computer[t.slug] = p.computer or "local"

        # Build all TodoItems once for width computation and reuse
        all_todo_items: list[TodoItem] = []
        icebox_items_by_project: dict[str, list[TodoItem]] = {}
        for p in self._projects_with_todos:
            for t in p.todos or []:
                item = TodoItem(
                    slug=t.slug,
                    status=TodoStatus(t.status) if t.status in {s.value for s in TodoStatus} else TodoStatus.PENDING,
                    description=t.description,
                    has_requirements=t.has_requirements,
                    has_impl_plan=t.has_impl_plan,
                    build_status=t.build_status,
                    review_status=t.review_status,
                    dor_score=t.dor_score,
                    deferrals_status=t.deferrals_status,
                    findings_count=t.findings_count,
                    files=t.files,
                    after=t.after,
                    group=t.group,
                    prepare_phase=t.prepare_phase,
                    integration_phase=t.integration_phase,
                    finalize_status=t.finalize_status,
                    project_path=t.project_path or p.path,
                )
                all_todo_items.append(item)
                if item.status == TodoStatus.ICEBOX:
                    icebox_items_by_project.setdefault(p.path, []).append(item)

        # Populate children_statuses for holder todos (active only)
        active_items = [t for t in all_todo_items if t.status != TodoStatus.ICEBOX]
        item_by_slug = {t.slug: t for t in active_items}
        for item in active_items:
            if item.group and item.group in item_by_slug:
                item_by_slug[item.group].children_statuses.append(item.status.value)

        slug_width = max((len(t.slug) for t in all_todo_items), default=0)
        col_widths = TodoRow.compute_col_widths(all_todo_items)

        # Build dependency tree from `after` graph (active items only)
        tree_nodes = build_dep_tree(active_items)
        max_depth = max((node.depth for node in tree_nodes), default=0) if tree_nodes else 0

        # Group projects by computer, preserving trusted_dirs order from config
        computer_order: list[str] = []
        computer_to_projects: dict[str, list[ProjectWithTodosDTO]] = {}
        for project in self._projects_with_todos:
            comp_name = project.computer or "local"
            if comp_name not in computer_to_projects:
                computer_order.append(comp_name)
                computer_to_projects[comp_name] = []
            computer_to_projects[comp_name].append(project)

        # Collect all widgets first, then batch-mount to minimize layout reflows
        widgets_to_mount: list[Widget] = []
        expanded_file_rows: list[tuple[TodoRow, list[Widget]]] = []

        for comp_name in computer_order:
            projects_in_comp = computer_to_projects[comp_name]

            # Count active todos (exclude icebox) across all projects under this computer
            comp_todo_count = sum(sum(1 for t in (p.todos or []) if t.status != "icebox") for p in projects_in_comp)
            comp_info = ComputerDTO(
                name=comp_name,
                status="online",
                user="",
                host=comp_name,
                is_local=(comp_name == "local"),
                tmux_binary="tmux",
            )
            comp_display = ComputerDisplayInfo(
                computer=comp_info,
                session_count=comp_todo_count,
                recent_activity=False,
            )
            comp_header = ComputerHeader(data=comp_display)
            widgets_to_mount.append(comp_header)
            self._nav_items.append(comp_header)

            for project in projects_in_comp:
                proj_info = ProjectDTO(
                    computer=project.computer,
                    name=project.name,
                    path=project.path,
                    description=project.description,
                )
                header = ProjectHeader(project=proj_info, session_count=0)
                widgets_to_mount.append(header)
                self._nav_items.append(header)

                # Filter tree nodes to this project's active todos
                project_slugs = {td.slug for td in (project.todos or []) if td.status != "icebox"}
                project_nodes = [node for node in tree_nodes if node.slug in project_slugs]

                for node in project_nodes:
                    # Depth-0 items always use ├─ because GroupSeparator closes the tree
                    is_last_sibling = False if node.depth == 0 else node.is_last

                    row = TodoRow(
                        todo=node.todo,
                        is_last=is_last_sibling,
                        slug_width=slug_width,
                        col_widths=col_widths,
                        tree_lines=node.tree_lines,
                        max_depth=max_depth,
                    )
                    widgets_to_mount.append(row)
                    self._nav_items.append(row)

                    # Collect file rows for expanded todos
                    if node.slug in self._expanded_todos and node.todo.files:
                        # File tree_lines = parent's lines + parent's own branch continuation
                        file_tree_lines = node.tree_lines + [not is_last_sibling]
                        sorted_files = sorted(node.todo.files)
                        file_widgets: list[Widget] = []
                        for fi, artifact_name in enumerate(sorted_files):
                            f_last = fi == len(sorted_files) - 1
                            file_row = TodoFileRow(
                                artifact_name=artifact_name,
                                filename=artifact_display_filename(artifact_name),
                                slug=node.slug,
                                project_path=project.path,
                                is_last=f_last,
                                tree_lines=file_tree_lines,
                            )
                            file_widgets.append(file_row)
                            widgets_to_mount.append(file_row)
                        expanded_file_rows.append((row, file_widgets))

                # Render icebox section when toggled on for this project
                project_icebox = icebox_items_by_project.get(project.path, [])
                show_icebox = project.path in self._icebox_projects and project_icebox
                if show_icebox:
                    # Match TodoRow total width after ├: ─(1) + square(1) + space(1) + slug + dots(2+indent) + columns
                    sep_width = 1 + 1 + 1 + slug_width + 2 + (max_depth * 2) + col_widths.get("_max", 0)
                    widgets_to_mount.append(IceboxSeparator(line_width=sep_width))
                    for ice_item in project_icebox:
                        # Depth-0: use ├─ (GroupSeparator closes the tree)
                        ice_row = TodoRow(
                            todo=ice_item,
                            is_last=False,
                            slug_width=slug_width,
                            col_widths=col_widths,
                            tree_lines=[],
                            max_depth=max_depth,
                        )
                        widgets_to_mount.append(ice_row)
                        self._nav_items.append(ice_row)

                if project_nodes or show_icebox:
                    widgets_to_mount.append(GroupSeparator(connector_col=ProjectHeader.CONNECTOR_COL))

        # Single batch mount - one layout reflow instead of N
        if widgets_to_mount:
            container.mount(*widgets_to_mount)

        # Insert file rows into nav_items at the correct positions
        for parent_row, file_ws in expanded_file_rows:
            row_idx = self._nav_items.index(parent_row)
            for i, fw in enumerate(file_ws):
                self._nav_items.insert(row_idx + 1 + i, fw)

        if self._nav_items and self.cursor_index >= len(self._nav_items):
            self.cursor_index = max(0, len(self._nav_items) - 1)
        self._update_cursor_highlight()
        self._logger.trace(
            "[PERF] PrepView._rebuild done items=%d dt=%.3f", len(self._nav_items), _t.monotonic() - _rb0
        )

    def _mount_file_rows(self, container: VerticalScroll, todo_row: TodoRow) -> None:
        """Mount file rows after a todo row and insert into nav_items."""
        sorted_files = sorted(todo_row.todo.files)
        row_idx = self._nav_items.index(todo_row)
        # File tree_lines = parent's lines + parent's own branch continuation
        file_tree_lines = list(todo_row._tree_lines) + [not todo_row.is_last]  # pylint: disable=protected-access
        project_path = todo_row.todo.project_path or self._resolve_project_root()
        for i, artifact_name in enumerate(sorted_files):
            is_last = i == len(sorted_files) - 1
            file_row = TodoFileRow(
                artifact_name=artifact_name,
                filename=artifact_display_filename(artifact_name),
                slug=todo_row.slug,
                project_path=project_path,
                is_last=is_last,
                tree_lines=file_tree_lines,
            )
            container.mount(file_row, after=todo_row if i == 0 else self._nav_items[row_idx + i])
            self._nav_items.insert(row_idx + 1 + i, file_row)

    def _remove_file_rows(self, todo_row: TodoRow) -> None:
        """Remove file rows belonging to a todo from container and nav_items."""
        row_idx = self._nav_items.index(todo_row)
        to_remove: list[TodoFileRow] = []
        for widget in self._nav_items[row_idx + 1 :]:
            if isinstance(widget, TodoFileRow) and widget.slug == todo_row.slug:
                to_remove.append(widget)
            else:
                break
        for widget in to_remove:
            self._nav_items.remove(widget)
            widget.remove()

    def _is_expanded(self, slug: str) -> bool:
        return slug in self._expanded_todos

    def _expand_todo(self, todo_row: TodoRow) -> None:
        """Expand a todo row - mount file rows."""
        slug = todo_row.slug
        if slug in self._expanded_todos:
            return
        self._expanded_todos.add(slug)
        self.post_message(StateChanged())
        if not todo_row.todo.files:
            return
        container = self.query_one("#preparation-scroll", VerticalScroll)
        self._mount_file_rows(container, todo_row)

    def _collapse_todo(self, todo_row: TodoRow) -> None:
        """Collapse a todo row - remove file rows."""
        slug = todo_row.slug
        if slug not in self._expanded_todos:
            return
        self._expanded_todos.discard(slug)
        self.post_message(StateChanged())
        self._remove_file_rows(todo_row)
        # Clamp cursor if it was on a removed file row
        if self.cursor_index >= len(self._nav_items):
            self.cursor_index = max(0, len(self._nav_items) - 1)
        self._update_cursor_highlight()

    def _update_cursor_highlight(self) -> None:
        for i, widget in enumerate(self._nav_items):
            was_selected = widget.has_class("selected")
            is_selected = i == self.cursor_index
            widget.set_class(is_selected, "selected")
            if was_selected != is_selected:
                widget.refresh()

    def _current_item(self) -> Widget | None:
        if not self._nav_items or self.cursor_index >= len(self._nav_items):
            return None
        return self._nav_items[self.cursor_index]

    def _current_todo_row(self) -> TodoRow | None:
        item = self._current_item()
        return item if isinstance(item, TodoRow) else None

    def _current_file_row(self) -> TodoFileRow | None:
        item = self._current_item()
        return item if isinstance(item, TodoFileRow) else None

    def _current_project_header(self) -> ProjectHeader | None:
        item = self._current_item()
        return item if isinstance(item, ProjectHeader) else None

    @staticmethod
    def _artifact_doc_id(project_path: str, slug: str, artifact_name: str) -> str:
        """Build a stable document id for a todo artifact."""
        return f"artifact:{project_path}:{slug}:{artifact_name}"

    def _editor_command(
        self,
        *,
        project_path: str,
        slug: str,
        artifact_name: str,
        view: bool = False,
    ) -> str:
        """Build an editor command that materializes a DB artifact into a temp file."""
        args = [
            sys.executable,
            "-m",
            "teleclaude.cli.editor",
            "--project-root",
            project_path,
            "--artifact-slug",
            slug,
            "--artifact-name",
            artifact_name,
        ]
        if view:
            args.append("--view")

        if self.app and self.app.theme:
            args.extend(["--theme", self.app.theme])

        return shlex.join(args)

    def _find_parent_todo(self, file_row: TodoFileRow) -> TodoRow | None:
        """Find the TodoRow that owns a file row."""
        idx = self._nav_items.index(file_row)
        for i in range(idx - 1, -1, -1):
            item = self._nav_items[i]
            if isinstance(item, TodoRow) and item.slug == file_row.slug:
                return item
        return None

    def _open_session_modal(
        self, *, computer: str, project_path: str, default_message: str, title: str | None = None
    ) -> None:
        """Open StartSessionModal with a pre-filled prompt."""
        modal = StartSessionModal(
            computer=computer,
            project_path=project_path,
            agent_availability=self._availability,
            default_message=default_message,
            title=title,
        )
        self.app.push_screen(modal, self._on_session_modal_result)

    def _on_session_modal_result(self, result: CreateSessionRequest | None) -> None:
        """Handle result from StartSessionModal."""
        if result:
            self.post_message(result)

    def _resolve_project_header_for_index(self, index: int) -> ProjectHeader | None:
        """Find nearest project header above a nav item index."""
        for i in range(index, -1, -1):
            item = self._nav_items[i]
            if isinstance(item, ProjectHeader):
                return item
        return None

    def _resolve_cursor_context(self) -> tuple[str, str, str | None] | None:  # pylint: disable=too-many-return-statements
        """Resolve computer, project path, and optional slug from cursor."""
        item = self._current_item()
        if item is None:
            return None

        if isinstance(item, ProjectHeader):
            return (item.project.computer or "local", item.project.path, None)

        if isinstance(item, TodoRow):
            slug = item.slug
            project_path = self._slug_to_project_path.get(slug, "")
            computer = self._slug_to_computer.get(slug, "local")
            if project_path:
                return (computer, project_path, slug)
            try:
                idx = self._nav_items.index(item)
            except ValueError:
                return None
            header = self._resolve_project_header_for_index(idx)
            if header:
                return (header.project.computer or "local", header.project.path, slug)
            return None

        if isinstance(item, TodoFileRow) and item.slug:
            slug = item.slug
            project_path = self._slug_to_project_path.get(slug, "")
            computer = self._slug_to_computer.get(slug, "local")
            if project_path:
                return (computer, project_path, slug)
            try:
                idx = self._nav_items.index(item)
            except ValueError:
                return None
            header = self._resolve_project_header_for_index(idx)
            if header:
                return (header.project.computer or "local", header.project.path, slug)
        return None

    def _resolve_todo_for_cursor(self) -> TodoRow | None:
        """Resolve selected todo row from todo/file cursor items."""
        todo_row = self._current_todo_row()
        if todo_row:
            return todo_row

        file_row = self._current_file_row()
        if file_row:
            return self._find_parent_todo(file_row)
        return None

    # --- Click handlers ---

    def on_computer_header_pressed(self, event: ComputerHeader.Pressed) -> None:
        """Handle click on a computer header - update cursor."""
        for i, widget in enumerate(self._nav_items):
            if widget is event.header:
                self.cursor_index = i
                self._update_cursor_highlight()
                break

    def on_todo_row_pressed(self, event: TodoRow.Pressed) -> None:
        """Handle click on a todo row - update cursor."""
        for i, widget in enumerate(self._nav_items):
            if widget is event.todo_row:
                self.cursor_index = i
                self._update_cursor_highlight()
                break

    def on_todo_file_row_pressed(self, event: TodoFileRow.Pressed) -> None:
        """Handle click on a file row - update cursor."""
        for i, widget in enumerate(self._nav_items):
            if widget is event.file_row:
                self.cursor_index = i
                self._update_cursor_highlight()
                break

    def on_project_header_pressed(self, event: ProjectHeader.Pressed) -> None:
        """Handle click on a project header - update cursor."""
        for i, widget in enumerate(self._nav_items):
            if widget is event.header:
                self.cursor_index = i
                self._update_cursor_highlight()
                break

    # --- State export ---

    def get_persisted_state(self) -> dict[str, object]:  # guard: loose-dict
        """Export the current expanded-todo and icebox state for persistence."""
        return {
            "expanded_todos": sorted(self._expanded_todos),
            "icebox_projects": sorted(self._icebox_projects),
        }


# Legacy stub for tests
class PrepTodoDisplayInfo:  # pylint: disable=too-few-public-methods
    """Minimal legacy todo display container kept for tests."""

    def __init__(self, todo: object, project_path: object, computer: object) -> None:
        self.todo = todo
        self.project_path = project_path
        self.computer = computer


class PrepTodoNode:  # pylint: disable=too-few-public-methods
    """Legacy empty todo node stub retained for compatibility."""


class PrepComputerDisplayInfo:  # pylint: disable=too-few-public-methods
    """Legacy empty computer display stub retained for compatibility."""


class PrepComputerNode:  # pylint: disable=too-few-public-methods
    """Legacy empty computer node stub retained for compatibility."""


class PrepFileDisplayInfo:  # pylint: disable=too-few-public-methods
    """Minimal legacy file display container kept for tests."""

    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class PrepFileNode:  # pylint: disable=too-few-public-methods
    """Legacy empty file node stub retained for compatibility."""


class PrepProjectDisplayInfo:  # pylint: disable=too-few-public-methods
    """Minimal legacy project display container kept for tests."""

    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class PrepProjectNode:  # pylint: disable=too-few-public-methods
    """Legacy empty project node stub retained for compatibility."""
