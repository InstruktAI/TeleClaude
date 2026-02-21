"""Preparation view with todo tree display."""

from __future__ import annotations

import time as _t

from instrukt_ai_logging import get_logger
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.models import AgentAvailabilityInfo, ProjectWithTodosInfo
from teleclaude.cli.tui.messages import (
    CreateSessionRequest,
    DocEditRequest,
    DocPreviewRequest,
)
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.widgets.group_separator import GroupSeparator
from teleclaude.cli.tui.widgets.modals import CreateTodoModal, StartSessionModal
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
from teleclaude.cli.tui.widgets.todo_row import TodoRow
from teleclaude.core.next_machine.core import DOR_READY_THRESHOLD


class PreparationView(Widget, can_focus=True):
    """Preparation tab view showing todo items grouped by project.

    Navigation: arrows, left/right expand/collapse, Enter = toggle expand,
    +/- expand/collapse all, p = prepare, s = start work.
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
        ("up", "cursor_up", "Previous"),
        ("down", "cursor_down", "Next"),
        ("left", "collapse", "Collapse"),
        ("right", "expand", "Expand"),
        ("enter", "activate", "Activate"),
        ("space", "preview_file", "Preview"),
        ("plus", "expand_all", "Expand all"),
        ("minus", "collapse_all", "Collapse all"),
        ("n", "new_todo", "New todo"),
        ("p", "prepare", "Prepare"),
        ("s", "start_work", "Start work"),
    ]

    cursor_index = reactive(0)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._projects_with_todos: list[ProjectWithTodosInfo] = []
        self._expanded_todos: set[str] = set()
        self._nav_items: list[Widget] = []
        self._slug_to_project_path: dict[str, str] = {}
        self._slug_to_computer: dict[str, str] = {}
        self._availability: dict[str, AgentAvailabilityInfo] = {}

    def compose(self) -> ComposeResult:
        scroll = VerticalScroll(id="preparation-scroll")
        scroll.can_focus = False
        yield scroll

    _logger = get_logger(__name__)

    def update_data(
        self,
        projects_with_todos: list[ProjectWithTodosInfo],
        availability: dict[str, AgentAvailabilityInfo] | None = None,
    ) -> None:
        """Update view with fresh API data. Only rebuild if structure changed."""
        self._logger.trace(
            "[PERF] PrepView.update_data called items=%d t=%.3f", len(projects_with_todos), _t.monotonic()
        )
        if availability is not None:
            self._availability = availability
        old_slugs = {t.slug for p in self._projects_with_todos for t in (p.todos or [])}
        new_slugs = {t.slug for p in projects_with_todos for t in (p.todos or [])}
        self._projects_with_todos = projects_with_todos
        if old_slugs != new_slugs or not self._nav_items:
            self._rebuild()

    def load_persisted_state(self, expanded_todos: set[str]) -> None:
        """Restore persisted expanded state."""
        self._expanded_todos = expanded_todos

    def _rebuild(self) -> None:
        """Rebuild the todo display from current data."""
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
        for p in self._projects_with_todos:
            for t in p.todos or []:
                all_todo_items.append(
                    TodoItem(
                        slug=t.slug,
                        status=TodoStatus(t.status)
                        if t.status in {s.value for s in TodoStatus}
                        else TodoStatus.PENDING,
                        description=t.description,
                        has_requirements=t.has_requirements,
                        has_impl_plan=t.has_impl_plan,
                        build_status=t.build_status,
                        review_status=t.review_status,
                        dor_score=t.dor_score,
                        deferrals_status=getattr(t, "deferrals_status", None),
                        findings_count=getattr(t, "findings_count", 0),
                        files=getattr(t, "files", []),
                        after=getattr(t, "after", []),
                        group=getattr(t, "group", None),
                    )
                )
        slug_width = max((len(t.slug) for t in all_todo_items), default=0)
        col_widths = TodoRow.compute_col_widths(all_todo_items)
        todo_by_slug: dict[str, TodoItem] = {t.slug: t for t in all_todo_items}

        # Compute dependency depth for indentation
        depth_map: dict[str, int] = {}
        visible_slugs = set(todo_by_slug.keys())

        def _depth(slug: str) -> int:
            if slug in depth_map:
                return depth_map[slug]
            item = todo_by_slug.get(slug)
            if not item or not item.after:
                depth_map[slug] = 0
                return 0
            parent_depths = [_depth(p) for p in item.after if p in visible_slugs]
            d = (max(parent_depths) + 1) if parent_depths else 0
            depth_map[slug] = d
            return d

        for item in all_todo_items:
            _depth(item.slug)
        max_depth = max(depth_map.values(), default=0)

        # Collect all widgets first, then batch-mount to minimize layout reflows
        widgets_to_mount: list[Widget] = []
        expanded_file_rows: list[tuple[TodoRow, list[Widget]]] = []

        for project in self._projects_with_todos:
            from teleclaude.cli.models import ProjectInfo

            proj_info = ProjectInfo(
                computer=project.computer,
                name=project.name,
                path=project.path,
                description=project.description,
            )
            header = ProjectHeader(project=proj_info, session_count=0)
            widgets_to_mount.append(header)
            self._nav_items.append(header)

            todos_list = project.todos or []
            depths = [depth_map.get(td.slug, 0) for td in todos_list]
            n_todos = len(todos_list)

            for idx, todo_data in enumerate(todos_list):
                todo = todo_by_slug[todo_data.slug]
                d = depths[idx]

                # Depth-0 items always use ├─ because GroupSeparator closes the tree.
                if d == 0:
                    is_last_sibling = False
                else:
                    is_last_sibling = True
                    for j in range(idx + 1, n_todos):
                        if depths[j] == d:
                            is_last_sibling = False
                            break
                        if depths[j] < d:
                            break

                # Ancestor continuation: for each level 0..d-1, check if a future
                # item at that level exists before a shallower item interrupts.
                # Level 0 is always True (GroupSeparator ┴ terminates the root line).
                tree_lines: list[bool] = []
                for lvl in range(d):
                    if lvl == 0:
                        tree_lines.append(True)
                        continue
                    has_cont = False
                    for j in range(idx + 1, n_todos):
                        if depths[j] == lvl:
                            has_cont = True
                            break
                        if depths[j] < lvl:
                            break
                    tree_lines.append(has_cont)

                row = TodoRow(
                    todo=todo,
                    is_last=is_last_sibling,
                    slug_width=slug_width,
                    col_widths=col_widths,
                    tree_lines=tree_lines,
                    max_depth=max_depth,
                )
                widgets_to_mount.append(row)
                self._nav_items.append(row)

                # Collect file rows for expanded todos
                if todo.slug in self._expanded_todos and todo.files:
                    # File tree_lines = parent's lines + parent's own branch continuation
                    file_tree_lines = tree_lines + [not is_last_sibling]
                    sorted_files = sorted(todo.files)
                    file_widgets: list[Widget] = []
                    for fi, filename in enumerate(sorted_files):
                        f_last = fi == len(sorted_files) - 1
                        file_row = TodoFileRow(
                            slug=todo.slug, filename=filename, is_last=f_last, tree_lines=file_tree_lines
                        )
                        file_widgets.append(file_row)
                        widgets_to_mount.append(file_row)
                    expanded_file_rows.append((row, file_widgets))

            if todos_list:
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
        file_tree_lines = list(todo_row._tree_lines) + [not todo_row.is_last]
        for i, filename in enumerate(sorted_files):
            is_last = i == len(sorted_files) - 1
            file_row = TodoFileRow(slug=todo_row.slug, filename=filename, is_last=is_last, tree_lines=file_tree_lines)
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

    def _editor_command(self, slug: str, filename: str, *, view: bool = False) -> str:
        """Build an editor command with absolute path for tmux pane."""
        project_path = self._slug_to_project_path.get(slug, "")
        if project_path:
            filepath = f"{project_path}/todos/{slug}/{filename}"
        else:
            filepath = f"todos/{slug}/{filename}"
        flag = " --view" if view else ""
        return f"uv run python -m teleclaude.cli.editor{flag} {filepath}"

    def _find_parent_todo(self, file_row: TodoFileRow) -> TodoRow | None:
        """Find the TodoRow that owns a file row."""
        idx = self._nav_items.index(file_row)
        for i in range(idx - 1, -1, -1):
            item = self._nav_items[i]
            if isinstance(item, TodoRow) and item.slug == file_row.slug:
                return item
        return None

    def _open_session_modal(self, slug: str, default_message: str) -> None:
        """Open StartSessionModal for a todo with a pre-filled prompt."""
        computer = self._slug_to_computer.get(slug, "local")
        project_path = self._slug_to_project_path.get(slug, "")
        if not project_path:
            return
        modal = StartSessionModal(
            computer=computer,
            project_path=project_path,
            agent_availability=self._availability,
            default_message=default_message,
        )
        self.app.push_screen(modal, self._on_session_modal_result)

    def _on_session_modal_result(self, result: CreateSessionRequest | None) -> None:
        """Handle result from StartSessionModal."""
        if result:
            self.post_message(result)

    # --- Keyboard actions ---

    def action_cursor_up(self) -> None:
        if self._nav_items and self.cursor_index > 0:
            self.cursor_index -= 1
            self._update_cursor_highlight()
            if 0 <= self.cursor_index < len(self._nav_items):
                self._nav_items[self.cursor_index].scroll_visible()

    def action_cursor_down(self) -> None:
        if self._nav_items and self.cursor_index < len(self._nav_items) - 1:
            self.cursor_index += 1
            self._update_cursor_highlight()
            if 0 <= self.cursor_index < len(self._nav_items):
                self._nav_items[self.cursor_index].scroll_visible()

    def action_expand(self) -> None:
        """Right: expand todo to show files."""
        row = self._current_todo_row()
        if row:
            self._expand_todo(row)

    def action_collapse(self) -> None:
        """Left: collapse todo or jump to parent todo from file row."""
        row = self._current_todo_row()
        if row:
            self._collapse_todo(row)
            return
        file_row = self._current_file_row()
        if file_row:
            parent = self._find_parent_todo(file_row)
            if parent:
                self._collapse_todo(parent)
                # Move cursor to parent
                try:
                    self.cursor_index = self._nav_items.index(parent)
                except ValueError:
                    pass
                self._update_cursor_highlight()

    def action_activate(self) -> None:
        """Enter: toggle expand/collapse on todo, open editor on file."""
        row = self._current_todo_row()
        if row:
            if self._is_expanded(row.slug):
                self._collapse_todo(row)
            else:
                self._expand_todo(row)
            return
        file_row = self._current_file_row()
        if file_row:
            self.post_message(
                DocEditRequest(
                    doc_id=f"todo:{file_row.slug}:{file_row.filename}",
                    command=self._editor_command(file_row.slug, file_row.filename),
                    title=f"Editing: {file_row.slug}/{file_row.filename}",
                )
            )

    def action_expand_all(self) -> None:
        for widget in list(self._nav_items):
            if isinstance(widget, TodoRow) and not self._is_expanded(widget.slug):
                self._expand_todo(widget)

    def action_collapse_all(self) -> None:
        for widget in list(self._nav_items):
            if isinstance(widget, TodoRow) and self._is_expanded(widget.slug):
                self._collapse_todo(widget)

    def action_preview_file(self) -> None:
        """Space: preview the current file in view mode (no focus)."""
        file_row = self._current_file_row()
        if file_row:
            self.post_message(
                DocPreviewRequest(
                    doc_id=f"todo:{file_row.slug}:{file_row.filename}",
                    command=self._editor_command(file_row.slug, file_row.filename, view=True),
                    title=f"{file_row.slug}/{file_row.filename}",
                )
            )

    def action_new_todo(self) -> None:
        """n: create a new todo via modal."""

        def _on_modal_result(slug: str | None) -> None:
            if not slug:
                return
            # Find project root from first known project path, or cwd
            project_root = None
            for path in self._slug_to_project_path.values():
                project_root = path
                break

            if not project_root:
                import os

                project_root = os.getcwd()

            from pathlib import Path

            from teleclaude.todo_scaffold import create_todo_skeleton

            try:
                create_todo_skeleton(Path(project_root), slug)
            except (ValueError, FileExistsError) as exc:
                self.app.notify(str(exc), severity="error")
                return

            # Open input.md in editor
            self.post_message(
                DocEditRequest(
                    doc_id=f"todo:{slug}:input.md",
                    command=self._editor_command(slug, "input.md"),
                    title=f"Editing: {slug}/input.md",
                )
            )

        self.app.push_screen(CreateTodoModal(), callback=_on_modal_result)

    def action_prepare(self) -> None:
        """p: directly start a prepare session with defaults."""
        row = self._current_todo_row()
        slug = row.slug if row else None
        if not slug:
            file_row = self._current_file_row()
            if file_row:
                slug = file_row.slug
        if not slug:
            return
        computer = self._slug_to_computer.get(slug, "local")
        project_path = self._slug_to_project_path.get(slug, "")
        if not project_path:
            return
        self.post_message(
            CreateSessionRequest(
                computer=computer,
                project_path=project_path,
                agent="claude",
                thinking_mode="slow",
                title=f"Prepare {slug}",
                message=f"/next-prepare {slug}",
            )
        )

    def action_start_work(self) -> None:
        """s: open agent session modal with /next-work prompt.

        Gated on DOR readiness - todo must meet DOR_READY_THRESHOLD.
        """
        row = self._current_todo_row()
        if not row:
            return
        dor = row.todo.dor_score
        if dor is None or dor < DOR_READY_THRESHOLD:
            self.app.notify(f"DOR score too low ({dor or 0}/{DOR_READY_THRESHOLD})", severity="warning")
            return
        self._open_session_modal(row.slug, f"/next-work {row.slug}")

    # --- Click handlers ---

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
        return {"expanded_todos": sorted(self._expanded_todos)}
