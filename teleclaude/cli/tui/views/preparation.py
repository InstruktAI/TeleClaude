"""Preparation view with todo tree display."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.cli.models import ProjectWithTodosInfo
from teleclaude.cli.tui.messages import DocPreviewRequest, TodoSelected
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.todo_row import TodoRow


class PreparationView(Widget):
    """Preparation tab view showing todo items grouped by project.

    Handles: arrow nav, Enter (expand/action), +/- (expand/collapse all),
    p (prepare), s (start work).
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
        ("enter", "toggle_expand", "Expand/action"),
        ("plus", "expand_all", "Expand all"),
        ("minus", "collapse_all", "Collapse all"),
        ("p", "prepare", "Prepare"),
        ("s", "start_work", "Start work"),
    ]

    cursor_index = reactive(0)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._projects_with_todos: list[ProjectWithTodosInfo] = []
        self._expanded_todos: set[str] = set()
        self._nav_items: list[Widget] = []

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="preparation-scroll")

    def update_data(self, projects_with_todos: list[ProjectWithTodosInfo]) -> None:
        """Update view with fresh API data and rebuild."""
        self._projects_with_todos = projects_with_todos
        self._rebuild()

    def load_persisted_state(self, expanded_todos: set[str]) -> None:
        """Restore persisted expanded state."""
        self._expanded_todos = expanded_todos

    def _rebuild(self) -> None:
        """Rebuild the todo display from current data."""
        container = self.query_one("#preparation-scroll", VerticalScroll)
        container.remove_children()
        self._nav_items.clear()

        for project in self._projects_with_todos:
            # Project header
            from teleclaude.cli.models import ProjectInfo

            proj_info = ProjectInfo(
                computer=project.computer,
                name=project.name,
                path=project.path,
                description=project.description,
            )
            header = ProjectHeader(project=proj_info, session_count=0)
            container.mount(header)
            self._nav_items.append(header)

            # Todo items
            for todo_data in project.todos or []:
                todo = TodoItem(
                    slug=todo_data.slug,
                    status=TodoStatus(todo_data.status)
                    if todo_data.status in {s.value for s in TodoStatus}
                    else TodoStatus.PENDING,
                    description=todo_data.description,
                    has_requirements=todo_data.has_requirements,
                    has_impl_plan=todo_data.has_impl_plan,
                    build_status=todo_data.build_status,
                    review_status=todo_data.review_status,
                    dor_score=todo_data.dor_score,
                    deferrals_status=getattr(todo_data, "deferrals_status", None),
                    findings_count=getattr(todo_data, "findings_count", 0),
                    files=getattr(todo_data, "files", []),
                )
                row = TodoRow(todo=todo)
                row.expanded = todo.slug in self._expanded_todos
                container.mount(row)
                self._nav_items.append(row)

        if self._nav_items and self.cursor_index >= len(self._nav_items):
            self.cursor_index = max(0, len(self._nav_items) - 1)
        self._update_cursor_highlight()

    def _update_cursor_highlight(self) -> None:
        for i, widget in enumerate(self._nav_items):
            widget.toggle_class("selected", i == self.cursor_index)

    def _current_todo_row(self) -> TodoRow | None:
        if not self._nav_items or self.cursor_index >= len(self._nav_items):
            return None
        item = self._nav_items[self.cursor_index]
        return item if isinstance(item, TodoRow) else None

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

    def action_toggle_expand(self) -> None:
        row = self._current_todo_row()
        if not row:
            return
        row.expanded = not row.expanded
        if row.expanded:
            self._expanded_todos.add(row.slug)
        else:
            self._expanded_todos.discard(row.slug)

    def action_expand_all(self) -> None:
        for widget in self._nav_items:
            if isinstance(widget, TodoRow):
                widget.expanded = True
                self._expanded_todos.add(widget.slug)

    def action_collapse_all(self) -> None:
        for widget in self._nav_items:
            if isinstance(widget, TodoRow):
                widget.expanded = False
        self._expanded_todos.clear()

    def action_prepare(self) -> None:
        """p: trigger preparation for selected todo."""
        row = self._current_todo_row()
        if row:
            self.post_message(TodoSelected(row.slug))

    def action_start_work(self) -> None:
        """s: start work on selected todo (opens doc preview)."""
        row = self._current_todo_row()
        if not row:
            return
        slug = row.slug
        if row.todo.has_impl_plan:
            self.post_message(
                DocPreviewRequest(
                    doc_id=f"todo:{slug}:impl",
                    command=f"glow todos/{slug}/implementation-plan.md",
                    title=f"Implementation: {slug}",
                )
            )
        elif row.todo.has_requirements:
            self.post_message(
                DocPreviewRequest(
                    doc_id=f"todo:{slug}:req",
                    command=f"glow todos/{slug}/requirements.md",
                    title=f"Requirements: {slug}",
                )
            )

    # --- State export ---

    def get_persisted_state(self) -> dict[str, object]:  # guard: loose-dict
        return {"expanded_todos": sorted(self._expanded_todos)}
