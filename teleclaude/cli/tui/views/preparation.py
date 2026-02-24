"""Preparation view with todo tree display."""

from __future__ import annotations

import time as _t

from instrukt_ai_logging import get_logger
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Footer

from teleclaude.cli.models import AgentAvailabilityInfo, ProjectWithTodosInfo
from teleclaude.cli.tui.messages import (
    CreateSessionRequest,
    DocEditRequest,
    DocPreviewRequest,
    StateDirty,
)
from teleclaude.cli.tui.prep_tree import build_dep_tree
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.widgets.group_separator import GroupSeparator
from teleclaude.cli.tui.widgets.modals import ConfirmModal, CreateSlugModal, StartSessionModal
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
from teleclaude.cli.tui.widgets.todo_row import TodoRow
from teleclaude.core.next_machine.core import DOR_READY_THRESHOLD


class PreparationView(Widget, can_focus=True):
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
        Binding("up", "cursor_up", "Up", key_display="↑", group=Binding.Group("Nav", compact=True)),
        Binding("down", "cursor_down", "Down", key_display="↓", group=Binding.Group("Nav", compact=True)),
        Binding("left", "collapse", "Collapse", key_display="←", group=Binding.Group("Fold", compact=True)),
        Binding("right", "expand", "Expand", key_display="→", group=Binding.Group("Fold", compact=True)),
        Binding("enter", "activate", "Toggle/Edit"),
        Binding("space", "preview_file", "View"),
        Binding("equals_sign", "expand_all", "All", key_display="+", group=Binding.Group("Fold", compact=True)),
        Binding("minus", "collapse_all", "None", key_display="-", group=Binding.Group("Fold", compact=True)),
        Binding("n", "new_todo", "Todo"),
        Binding("b", "new_bug", "Bug"),
        Binding("p", "prepare", "Prep"),
        Binding("s", "start_work", "Start"),
        Binding("R", "remove_todo", "Remove"),
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

    @staticmethod
    def _todo_fingerprint(projects: list[ProjectWithTodosInfo]) -> tuple[tuple[str, ...], ...]:
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
                ",".join(t.files),
                ",".join(t.after),
                t.group or "",
            )
            for p in projects
            for t in (p.todos or [])
        )

    def update_data(
        self,
        projects_with_todos: list[ProjectWithTodosInfo],
        availability: dict[str, AgentAvailabilityInfo] | None = None,
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

        # Build dependency tree from `after` graph
        tree_nodes = build_dep_tree(all_todo_items)
        max_depth = max((node.depth for node in tree_nodes), default=0) if tree_nodes else 0

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

            if getattr(project, "has_roadmap", False):
                roadmap_row = TodoFileRow(
                    filepath=f"{project.path}/todos/roadmap.yaml",
                    filename="roadmap.yaml",
                    slug="",
                    is_last=False,
                    tree_lines=[],
                )
                widgets_to_mount.append(roadmap_row)
                self._nav_items.append(roadmap_row)

            # Filter tree nodes to this project's todos
            project_slugs = {td.slug for td in (project.todos or [])}
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
                    # Get project path for filepath construction
                    proj_path = self._slug_to_project_path.get(node.slug, "")
                    for fi, filename in enumerate(sorted_files):
                        f_last = fi == len(sorted_files) - 1
                        filepath = (
                            f"{proj_path}/todos/{node.slug}/{filename}"
                            if proj_path
                            else f"todos/{node.slug}/{filename}"
                        )
                        file_row = TodoFileRow(
                            filepath=filepath,
                            filename=filename,
                            slug=node.slug,
                            is_last=f_last,
                            tree_lines=file_tree_lines,
                        )
                        file_widgets.append(file_row)
                        widgets_to_mount.append(file_row)
                    expanded_file_rows.append((row, file_widgets))

            if project_nodes:
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
        # Get project path for filepath construction
        proj_path = self._slug_to_project_path.get(todo_row.slug, "")
        for i, filename in enumerate(sorted_files):
            is_last = i == len(sorted_files) - 1
            filepath = (
                f"{proj_path}/todos/{todo_row.slug}/{filename}" if proj_path else f"todos/{todo_row.slug}/{filename}"
            )
            file_row = TodoFileRow(
                filepath=filepath,
                filename=filename,
                slug=todo_row.slug,
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
        self.post_message(StateDirty())
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
        self.post_message(StateDirty())
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

    def _editor_command(self, filepath: str, *, view: bool = False) -> str:
        """Build an editor command with absolute path for tmux pane."""
        flags = []
        if view:
            flags.append("--view")

        # Pass current theme to editor subprocess so it matches the TUI
        if self.app and self.app.theme:
            flags.append(f"--theme {self.app.theme}")

        flag_str = " " + " ".join(flags) if flags else ""
        return f"uv run python -m teleclaude.cli.editor{flag_str} {filepath}"

    def _find_parent_todo(self, file_row: TodoFileRow) -> TodoRow | None:
        """Find the TodoRow that owns a file row."""
        idx = self._nav_items.index(file_row)
        for i in range(idx - 1, -1, -1):
            item = self._nav_items[i]
            if isinstance(item, TodoRow) and item.slug == file_row.slug:
                return item
        return None

    def _open_session_modal(self, *, computer: str, project_path: str, default_message: str) -> None:
        """Open StartSessionModal with a pre-filled prompt."""
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

    def _resolve_project_header_for_index(self, index: int) -> ProjectHeader | None:
        """Find nearest project header above a nav item index."""
        for i in range(index, -1, -1):
            item = self._nav_items[i]
            if isinstance(item, ProjectHeader):
                return item
        return None

    def _resolve_cursor_context(self) -> tuple[str, str, str | None] | None:
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

    @staticmethod
    def _next_command(base: str, slug: str | None) -> str:
        """Build /next-* command with optional slug."""
        return f"/{base} {slug}" if slug else f"/{base}"

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

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Enable/hide actions based on current tree node type."""
        del parameters
        item = self._current_item()

        if isinstance(item, ProjectHeader):
            if action in {"remove_todo", "activate", "preview_file"}:
                return False
            return True

        if isinstance(item, TodoRow):
            if action == "preview_file":
                return False
            return True

        if isinstance(item, TodoFileRow):
            if action in {"new_todo", "new_bug"}:
                return False
            return True

        return True

    def watch_cursor_index(self, _index: int) -> None:
        """Refresh key bindings when node context changes."""
        if self.is_attached:
            self.app.refresh_bindings()
            self.call_after_refresh(self._sync_default_footer_action)

    def _default_footer_action(self) -> str | None:
        """Return the primary action for the selected node."""
        item = self._current_item()
        if isinstance(item, ProjectHeader):
            return "new_todo"
        if isinstance(item, (TodoRow, TodoFileRow)):
            return "activate"
        return None

    def _sync_default_footer_action(self) -> None:
        """Mark the active default action in Footer."""
        if not self.is_attached:
            return
        try:
            footer = self.app.query_one(Footer)
        except Exception:
            return
        default_action = self._default_footer_action()
        for key_widget in footer.query("FooterKey"):
            key_widget.set_class(getattr(key_widget, "action", None) == default_action, "default-action")

    def on_focus(self) -> None:
        """Sync default footer styling when the view receives focus."""
        self.app.refresh_bindings()
        self.call_after_refresh(self._sync_default_footer_action)

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
                    doc_id=file_row.filepath,
                    command=self._editor_command(file_row.filepath),
                    title=f"Editing: {file_row.filename}",
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
                    doc_id=file_row.filepath,
                    command=self._editor_command(file_row.filepath, view=True),
                    title=file_row.filename,
                )
            )

    def _resolve_project_root(self) -> str:
        """Resolve project root from known project paths or cwd."""
        for path in self._slug_to_project_path.values():
            return path
        import os

        return os.getcwd()

    def _create_item(self, slug: str, *, kind: str) -> None:
        """Scaffold a todo or bug and open its primary file in the editor."""
        from pathlib import Path

        project_root = self._resolve_project_root()

        if kind == "bug":
            from teleclaude.todo_scaffold import create_bug_skeleton

            try:
                create_bug_skeleton(Path(project_root), slug, description="")
            except (ValueError, FileExistsError) as exc:
                self.app.notify(str(exc), severity="error")
                return
            filename = "bug.md"
        else:
            from teleclaude.todo_scaffold import create_todo_skeleton

            try:
                create_todo_skeleton(Path(project_root), slug)
            except (ValueError, FileExistsError) as exc:
                self.app.notify(str(exc), severity="error")
                return
            filename = "input.md"

        filepath = f"{project_root}/todos/{slug}/{filename}"
        self.post_message(
            DocEditRequest(
                doc_id=filepath,
                command=self._editor_command(filepath),
                title=f"Editing: {slug}/{filename}",
            )
        )

    def action_new_todo(self) -> None:
        """n: create a new todo via modal."""

        def _on_result(slug: str | None) -> None:
            if slug:
                self._create_item(slug, kind="todo")

        self.app.push_screen(CreateSlugModal(title="New Todo"), callback=_on_result)

    def action_new_bug(self) -> None:
        """b: create a new bug via modal."""

        def _on_result(slug: str | None) -> None:
            if slug:
                self._create_item(slug, kind="bug")

        self.app.push_screen(CreateSlugModal(title="New Bug", placeholder="my-new-bug"), callback=_on_result)

    def action_remove_todo(self) -> None:
        """R: remove a todo and all its files."""
        from pathlib import Path

        from teleclaude.todo_scaffold import remove_todo

        # Resolve slug from current row (todo or file)
        row = self._current_todo_row()
        slug = row.slug if row else None
        if not slug:
            file_row = self._current_file_row()
            if file_row:
                slug = file_row.slug
        if not slug:
            return

        # Resolve project root
        project_path = self._slug_to_project_path.get(slug, "")
        if not project_path:
            return
        project_root = Path(project_path)

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                remove_todo(project_root, slug)
                self.app.notify(f"Removed {slug}")
            except (ValueError, RuntimeError, FileNotFoundError) as exc:
                self.app.notify(str(exc), severity="error")

        self.app.push_screen(
            ConfirmModal(
                title="Remove Todo",
                message=f"Remove todo '{slug}' and all its files?\n\nThis action cannot be undone.",
            ),
            _on_confirm,
        )

    def action_prepare(self) -> None:
        """p: open session modal prefilled with /next-prepare [slug]."""
        context = self._resolve_cursor_context()
        if not context:
            return
        computer, project_path, slug = context
        self._open_session_modal(
            computer=computer,
            project_path=project_path,
            default_message=self._next_command("next-prepare", slug),
        )

    def action_start_work(self) -> None:
        """s: open session modal prefilled with /next-work [slug].

        Gated on DOR readiness when a specific todo is selected.
        """
        context = self._resolve_cursor_context()
        if not context:
            return
        computer, project_path, slug = context

        if slug:
            todo_row = self._resolve_todo_for_cursor()
            if not todo_row:
                return
            dor = todo_row.todo.dor_score
            if dor is None or dor < DOR_READY_THRESHOLD:
                self.app.notify(f"DOR score too low ({dor or 0}/{DOR_READY_THRESHOLD})", severity="warning")
                return

        self._open_session_modal(
            computer=computer,
            project_path=project_path,
            default_message=self._next_command("next-work", slug),
        )

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


# Legacy stub for tests
class PrepTodoDisplayInfo:
    def __init__(self, todo: object, project_path: object, computer: object) -> None:
        self.todo = todo
        self.project_path = project_path
        self.computer = computer


class PrepTodoNode:
    pass


class PrepComputerDisplayInfo:
    pass


class PrepComputerNode:
    pass


class PrepFileDisplayInfo:
    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class PrepFileNode:
    pass


class PrepProjectDisplayInfo:
    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class PrepProjectNode:
    pass
