"""Preparation view with todo tree display."""

from __future__ import annotations

import shlex
import sys
import time as _t
from typing import TYPE_CHECKING, NamedTuple

from instrukt_ai_logging import get_logger
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget

from teleclaude.api_models import (
    AgentAvailabilityDTO,
    ComputerDTO,
    ProjectDTO,
    ProjectWithTodosDTO,
    SessionDTO,
    TodoDTO,
)
from teleclaude.cli.tui.artifact_panes import (
    EDITOR_MODULE,
    FLAG_ARTIFACT_NAME,
    FLAG_ARTIFACT_SLUG,
    FLAG_ARTIFACT_TODO_ID,
    FLAG_MODULE,
    FLAG_PROJECT_ROOT,
    FLAG_THEME,
    FLAG_VIEW,
    artifact_doc_id,
)
from teleclaude.cli.tui.creator_session import (
    MISSING_SESSION_STATUS,
    SessionInfo,
    SessionLookup,
    SessionStatus,
    resolve_creator_row_state,
    resolve_session_row_state,
)
from teleclaude.cli.tui.messages import CreateSessionRequest, StateChanged, TodoSelected
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.tree import (
    ComputerDisplayInfo,
    _computer_order_key,
    _is_local_name,
    parse_collapsed_projects,
    project_collapse_key,
)
from teleclaude.cli.tui.views.preparation_actions import (
    RETAINED_TODO_STATUSES,
    PreparationAction,
    PreparationViewActionsMixin,
)
from teleclaude.cli.tui.widgets.chip import ownership_surface_enabled, principal_to_email
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.delivered_separator import DeliveredSeparator
from teleclaude.cli.tui.widgets.group_separator import GroupSeparator
from teleclaude.cli.tui.widgets.icebox_separator import IceboxSeparator
from teleclaude.cli.tui.widgets.modals import StartSessionModal
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.todo_creation_record_row import TodoSessionRow
from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
from teleclaude.cli.tui.widgets.todo_row import DEPENDENCY_FLASH_CLASS, TodoRow
from teleclaude.cli.tui.widgets.trashed_separator import TrashedSeparator
from teleclaude.config import config
from teleclaude.constants import TodoStatus
from teleclaude.core.todo_tree import FlatRow, build_todo_sections, flatten
from teleclaude.todo_artifacts import artifact_display_filename
from teleclaude.types.creation_record import Lineage

_UNKNOWN_TODO_STATUS_EVENT = "tui.todo_status_unknown"
DEPENDENCY_FLASH_DURATION_S = 1.5
DEPENDENCY_FLASH_KEY = "D"
DEPENDENCY_FLASH_LABEL = "Deps"

if TYPE_CHECKING:
    from textual.timer import Timer


_CREATOR_SESSION_LABEL = "created in"
_PREPARED_SESSION_LABEL = "prepped in"
_ARTIFACT_TIMESTAMP_SEPARATOR = ":"
_EMPTY_SESSION_ROW_FINGERPRINT = ("", "")
_RETAINED_TODO_STATUS_VALUES = frozenset(status.value for status in RETAINED_TODO_STATUSES)


class _PreparationCursorContext(NamedTuple):
    computer: str
    project_path: str
    slug: str | None
    todo_id: str | None


def _session_row_fingerprint(session_id: str | None, lookup: SessionLookup) -> tuple[str, str]:
    """Return the (session_id, status) pair driving one provenance row, or blanks when none."""
    state = resolve_session_row_state(session_id, lookup)
    if state is None:
        return _EMPTY_SESSION_ROW_FINGERPRINT
    return (state.session_id, state.status or MISSING_SESSION_STATUS)


_ROW_KEY_SEPARATOR = ":"
_ROW_KEY_TODO = "todo"
_ROW_KEY_FILE = "file"


def _row_key(widget: Widget) -> str | None:
    """Identity of a navigable row, stable across a rebuild.

    Rows that stand for a durable thing — a todo or one of its artifacts — can
    be found again after the tree is rebuilt. A header or
    separator has no identity beyond its position, so it has no key and the
    cursor falls back to its clamped index.
    """
    if isinstance(widget, TodoFileRow):
        return _ROW_KEY_SEPARATOR.join((_ROW_KEY_FILE, widget.todo_id, widget.artifact_name))
    if isinstance(widget, TodoRow):
        todo_id = widget.todo.todo_id
        if todo_id is not None:
            return _ROW_KEY_SEPARATOR.join((_ROW_KEY_TODO, todo_id))
    return None


class PreparationView(PreparationViewActionsMixin, Widget, can_focus=True):
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
        Binding("space", "preview_file", "View", show=False),
        Binding(
            "equals_sign", "expand_all", "All", key_display="+", group=Binding.Group("Fold", compact=True), show=False
        ),
        Binding(
            "minus", "collapse_all", "None", key_display="-", group=Binding.Group("Fold", compact=True), show=False
        ),
        Binding("plus", "expand_structure", "Expand tree", show=False),
        Binding("underscore", "collapse_structure", "Collapse tree", show=False),
        Binding("n", "new_todo", "Todo"),
        Binding("N", "new_project", "Project"),
        Binding("b", "new_bug", "Bug"),
        Binding("p", "prepare", "Prep"),
        Binding("s", "start_work", "Strt"),
        Binding("R", "remove_artifact", "Remv"),
        Binding("U", "reactivate_selected", "Unr"),
        Binding("f", "freeze", "Frz"),
        Binding("u", "unfreeze", "Unfr"),
        Binding("A", "approve_gate", "Appr"),
        Binding("h", "hold", "Hold/Unhold"),
        Binding("d", "toggle_delivered", "Deliv"),
        Binding("i", "toggle_icebox", "Ice"),
        Binding("x", "toggle_trashed", "Trsh"),
        Binding(DEPENDENCY_FLASH_KEY, PreparationAction.FLASH_DEPENDENCIES, DEPENDENCY_FLASH_LABEL, show=False),
    ]

    cursor_index = reactive(0)
    persistence_key = "preparation"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._projects_with_todos: list[ProjectWithTodosDTO] = []
        self._expanded_todos: set[str] = set()
        self._collapsed_computers: set[str] = set()
        self._collapsed_projects: set[tuple[str, str]] = set()
        self._icebox_projects: set[str] = set()
        self._delivered_projects: set[str] = set()
        self._trashed_projects: set[str] = set()
        self._highlighted_row_key: str | None = None
        self._todo_state_pruned = False
        self._nav_items: list[Widget] = []
        self._availability: dict[str, AgentAvailabilityDTO] = {}
        self._human_filter: str | None = None
        self._session_lookup: SessionLookup = {}
        self._detail_rows: dict[str, list[Widget]] = {}
        self._dependency_flash_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        scroll = VerticalScroll(id="preparation-scroll")
        scroll.can_focus = False
        yield scroll

    def _clear_dependency_flash(self) -> None:
        """Remove the transient dependency flash and stop its timer."""
        if self._dependency_flash_timer is not None:
            self._dependency_flash_timer.stop()
            self._dependency_flash_timer = None
        for widget in self._nav_items:
            if isinstance(widget, TodoRow) and widget.has_class(DEPENDENCY_FLASH_CLASS):
                widget.set_class(False, DEPENDENCY_FLASH_CLASS)
                widget.refresh()

    def _flash_dependencies(self) -> None:
        """Highlight displayed additional dependencies of the selected todo."""
        self._clear_dependency_flash()
        selected_row = self._current_todo_row()
        if selected_row is None:
            return
        dependency_slugs = set(selected_row.todo.after)
        if not dependency_slugs:
            return
        selected_project = project_collapse_key(selected_row.todo.computer, selected_row.todo.project_path)
        visual_parent_id = selected_row.todo.visual_dependency_parent_id
        has_flash = False
        for widget in self._nav_items:
            if (
                not isinstance(widget, TodoRow)
                or not widget.display
                or project_collapse_key(widget.todo.computer, widget.todo.project_path) != selected_project
                or widget.todo.slug not in dependency_slugs
                or widget.todo.todo_id == visual_parent_id
            ):
                continue
            widget.set_class(True, DEPENDENCY_FLASH_CLASS)
            widget.refresh()
            has_flash = True
        if has_flash:
            self._dependency_flash_timer = self.set_timer(DEPENDENCY_FLASH_DURATION_S, self._clear_dependency_flash)

    def on_unmount(self) -> None:
        """Stop the transient dependency flash when the view leaves the DOM."""
        self._clear_dependency_flash()

    _logger = get_logger(__name__)

    @staticmethod
    def _project_fingerprint(projects: list[ProjectWithTodosDTO]) -> tuple[tuple[str, str], ...]:
        """Identity + order of the projects/computers, independent of todo content.

        ``_todo_fingerprint`` skips empty-todo projects, so an authoritative
        full project/computer set arriving after a partial-state render would
        not repaint on todo content alone. This captures each project's owning
        computer and path in order so a changed set or order forces a rebuild.
        """
        return tuple((p.computer or "local", p.path) for p in projects)

    def _todo_fingerprint(self, projects: list[ProjectWithTodosDTO]) -> tuple[tuple[str, ...], ...]:
        """Build a lightweight fingerprint of all todo data for change detection.

        Includes the creator-session row state so a lookup transition (e.g. a
        retained-closed session becoming live after revive, or purged past
        retention) forces a rebuild even when the todo's own fields are
        unchanged.
        """
        lookup = self._session_lookup
        return tuple(
            (
                t.slug,
                t.status,
                t.build_status or "",
                t.review_status or "",
                t.deferrals_status or "",
                str(t.has_requirements),
                str(t.has_impl_plan),
                ",".join(t.files),
                ",".join(
                    _ARTIFACT_TIMESTAMP_SEPARATOR.join((name, updated_at))
                    for name, updated_at in sorted(t.artifact_updated_at.items())
                ),
                str(getattr(t, "version_total", 0)),
                ",".join(t.after),
                t.group or "",
                getattr(t, "lifecycle_phase", None) or "",
                getattr(t, "integration_phase", None) or "",
                getattr(t, "finalize_status", None) or "",
                "1" if getattr(t, "hold", False) else "0",
                "1" if getattr(t, "held", False) else "0",
                getattr(t, "hold_source", None) or "",
                getattr(t, "active_runner", None) or "",
                getattr(t, "schedule", None) or "",
                getattr(t, "task_plan_digest", None) or "",
                getattr(t, "task_approved_digest", None) or "",
                getattr(t, "band", None) or "",
                getattr(t, "ready_since", None) or "",
                getattr(t, "updated_at", None) or "",
                getattr(t, "todo_id", None) or "",
                getattr(t, "removed_at", None) or "",
                *_session_row_fingerprint(Lineage.parse(t.lineage or "").acting_session, lookup),
                *_session_row_fingerprint(t.prepared_session_id, lookup),
            )
            for p in projects
            for t in (p.todos or [])
        )

    def update_data(
        self,
        projects_with_todos: list[ProjectWithTodosDTO],
        session_lookup: SessionLookup | None = None,
    ) -> None:
        """Update view with fresh API data. Only rebuild if data changed."""
        self._logger.trace(
            "[PERF] PrepView.update_data called items=%d t=%.3f", len(projects_with_todos), _t.monotonic()
        )
        old_fp = self._todo_fingerprint(self._projects_with_todos)
        old_proj_fp = self._project_fingerprint(self._projects_with_todos)
        if session_lookup is not None:
            self._session_lookup = session_lookup
        new_fp = self._todo_fingerprint(projects_with_todos)
        new_proj_fp = self._project_fingerprint(projects_with_todos)
        self._projects_with_todos = projects_with_todos
        todos = [todo for project in projects_with_todos for todo in (project.todos or [])]
        if not self._todo_state_pruned and todos:
            self._prune_stale_todo_state(todos)
            self._todo_state_pruned = True
        if old_fp != new_fp or old_proj_fp != new_proj_fp or not self._nav_items:
            self._rebuild()

    def set_availability(self, availability: dict[str, AgentAvailabilityDTO]) -> None:
        """Update cached agent availability without rebuilding the view."""
        self._availability = availability

    def update_session(
        self,
        session_id: str,
        *,
        status: SessionStatus,
        computer: str | None,
    ) -> None:
        """Apply one pushed session lifecycle delta."""
        existing = self._session_lookup.get(session_id)
        resolved_computer = computer if computer is not None else existing.computer if existing else None
        info = SessionInfo(status=status, computer=resolved_computer)
        if existing == info:
            return
        lookup = dict(self._session_lookup)
        lookup[session_id] = info
        self.update_data(self._projects_with_todos, session_lookup=lookup)

    def reconcile_sessions(self, sessions: list[SessionDTO], *, computer: str | None) -> None:
        """Reconcile provenance-session liveness from a pushed authoritative snapshot."""
        live_ids = {session.session_id for session in sessions}
        lookup = dict(self._session_lookup)

        def in_scope(value: str | None) -> bool:
            if computer is None:
                return True
            if _is_local_name(computer, config.computer.name):
                return _is_local_name(value or "", config.computer.name)
            return value == computer

        for session_id, info in tuple(lookup.items()):
            if info.status == "live" and in_scope(info.computer) and session_id not in live_ids:
                lookup.pop(session_id, None)
        for session in sessions:
            lookup[session.session_id] = SessionInfo(status="live", computer=session.computer)

        if lookup != self._session_lookup:
            self.update_data(self._projects_with_todos, session_lookup=lookup)

    def _prune_stale_todo_state(self, todos: list[TodoDTO]) -> None:
        """Migrate slug-keyed view state to durable ids from the first payload."""
        present_ids = {todo.todo_id for todo in todos if todo.todo_id is not None}
        live_ids_by_slug: dict[str, list[str]] = {}
        for todo in todos:
            if todo.todo_id is None or todo.status in _RETAINED_TODO_STATUS_VALUES:
                continue
            live_ids_by_slug.setdefault(todo.slug, []).append(todo.todo_id)

        def unique_live_id(slug: str) -> str | None:
            """Resolve only when a legacy slug has one current live row."""
            matches = live_ids_by_slug.get(slug, [])
            return matches[0] if len(matches) == 1 else None

        migrated_expanded: set[str] = set()
        for value in self._expanded_todos:
            if value in present_ids:
                migrated_expanded.add(value)
                continue
            todo_id = unique_live_id(value)
            if todo_id is not None:
                migrated_expanded.add(todo_id)
        self._expanded_todos = migrated_expanded

        if self._highlighted_row_key is None:
            return
        parts = self._highlighted_row_key.split(_ROW_KEY_SEPARATOR, 2)
        if len(parts) == 2 and parts[0] == _ROW_KEY_TODO:
            if parts[1] in present_ids:
                return
            todo_id = unique_live_id(parts[1])
            self._highlighted_row_key = (
                _ROW_KEY_SEPARATOR.join((_ROW_KEY_TODO, todo_id)) if todo_id is not None else None
            )
            return
        if len(parts) == 3 and parts[0] == _ROW_KEY_FILE:
            if parts[1] in present_ids:
                return
            todo_id = unique_live_id(parts[1])
            self._highlighted_row_key = (
                _ROW_KEY_SEPARATOR.join((_ROW_KEY_FILE, todo_id, parts[2])) if todo_id is not None else None
            )
            return
        self._highlighted_row_key = None

    def load_persisted_state(self, data: dict[str, object]) -> None:  # guard: loose-dict
        """Restore persisted expanded and icebox state."""
        expanded_todos = data.get("expanded_todos", [])
        if isinstance(expanded_todos, list):
            self._expanded_todos = {str(item) for item in expanded_todos}
        collapsed_computers = data.get("collapsed_computers", [])
        if isinstance(collapsed_computers, list):
            self._collapsed_computers = {str(item) for item in collapsed_computers}
        self._collapsed_projects = parse_collapsed_projects(data.get("collapsed_projects", []))
        icebox_projects = data.get("icebox_projects", [])
        if isinstance(icebox_projects, list):
            self._icebox_projects = {str(item) for item in icebox_projects}
        delivered_projects = data.get("delivered_projects", [])
        if isinstance(delivered_projects, list):
            self._delivered_projects = {str(item) for item in delivered_projects}
        trashed_projects = data.get("trashed_projects", [])
        if isinstance(trashed_projects, list):
            self._trashed_projects = {str(item) for item in trashed_projects}
        highlighted_row_key = data.get("highlighted_row_key")
        if isinstance(highlighted_row_key, str):
            self._highlighted_row_key = highlighted_row_key

    def _rebuild(self) -> None:  # noqa: C901
        """Rebuild the todo display from current data (Computer → Project → Todo)."""
        _rb0 = _t.monotonic()
        self._logger.trace("[PERF] PrepView._rebuild START t=%.3f", _rb0)
        self._clear_dependency_flash()
        container = self.query_one("#preparation-scroll", VerticalScroll)
        container.remove_children()
        self._nav_items.clear()
        self._detail_rows.clear()

        def _item_from_dto(
            dto: TodoDTO,
            *,
            project_path: str,
            is_holder: bool = False,
            computer: str | None = None,
            visual_dependency_parent_id: str | None = None,
        ) -> TodoItem:
            try:
                status: TodoStatus | str = TodoStatus(dto.status)
            except ValueError:
                self._logger.warning(
                    _UNKNOWN_TODO_STATUS_EVENT,
                    slug=dto.slug,
                    project_path=dto.project_path or project_path,
                    raw_status=dto.status,
                )
                status = dto.status
            return TodoItem(
                slug=dto.slug,
                status=status,
                description=dto.description,
                has_requirements=dto.has_requirements,
                has_impl_plan=dto.has_impl_plan,
                build_status=dto.build_status,
                review_status=dto.review_status,
                prepare_review_verdict=dto.prepare_review_verdict,
                deferrals_status=dto.deferrals_status,
                files=dto.files,
                artifact_updated_at=dto.artifact_updated_at,
                version_total=dto.version_total,
                after=dto.after,
                group=dto.group,
                kind=dto.kind,
                lifecycle_phase=dto.lifecycle_phase,
                integration_phase=dto.integration_phase,
                finalize_status=dto.finalize_status,
                hold=dto.hold,
                held=dto.held,
                hold_source=dto.hold_source,
                active_runner=dto.active_runner,
                prepared_session_id=dto.prepared_session_id,
                schedule=dto.schedule,
                task_plan_digest=dto.task_plan_digest,
                task_approved_digest=dto.task_approved_digest,
                project_path=dto.project_path or project_path,
                computer=computer,
                visual_dependency_parent_id=visual_dependency_parent_id,
                todo_id=dto.todo_id,
                removed_at=dto.removed_at,
                delivered_at=dto.delivered_at,
                is_holder=is_holder,
                lineage=dto.lineage,
                entry_point=dto.entry_point,
                human_involved=dto.human_involved,
            )

        # Sectioned dependency trees come from the projection — the view renders;
        # it does not derive hierarchy, grouping, or section membership.
        project_sections = {
            project_collapse_key(p.computer, p.path): build_todo_sections(list(p.todos or []))
            for p in self._projects_with_todos
        }

        # Widths are computed per rendered section: rows align with, and
        # reserve state-column slots for, only the section they render in — a
        # scheduled, autonomous, or held todo elsewhere costs no cells here.
        def _section_metrics(
            rows: list[FlatRow], project_path: str, computer: str | None = None
        ) -> tuple[int, dict[str, int], int]:
            items = [
                _item_from_dto(r.todo, project_path=project_path, is_holder=r.is_holder, computer=computer)
                for r in rows
            ]
            slug_width = max((len(i.slug) for i in items), default=0)
            max_depth = max((r.depth for r in rows), default=0)
            return slug_width, TodoRow.compute_col_widths(items), max_depth

        def _emit_row(
            row: FlatRow,
            project_path: str,
            computer: str | None,
            metrics: tuple[int, dict[str, int], int],
        ) -> None:
            # Depth-0 items always use ├─ because GroupSeparator closes the tree
            is_last = False if row.depth == 0 else row.is_last
            slug_width, col_widths, max_depth = metrics
            item = _item_from_dto(
                row.todo,
                project_path=project_path,
                is_holder=row.is_holder,
                computer=computer,
                visual_dependency_parent_id=row.visual_dependency_parent_id,
            )
            todo_row = TodoRow(
                todo=item,
                is_last=is_last,
                slug_width=slug_width,
                col_widths=col_widths,
                tree_lines=row.tree_lines,
                max_depth=max_depth,
            )
            widgets_to_mount.append(todo_row)
            self._nav_items.append(todo_row)
            todo_id = row.todo.todo_id
            if todo_id is not None and todo_id in self._expanded_todos:
                detail_tree_lines = [*row.tree_lines, not is_last]
                sorted_files = sorted(item.files)
                creator_state = resolve_creator_row_state(item.lineage, self._session_lookup)
                prepared_state = resolve_session_row_state(item.prepared_session_id, self._session_lookup)
                detail_widgets: list[Widget] = []
                provenance_rows = [
                    (_CREATOR_SESSION_LABEL, creator_state),
                    (_PREPARED_SESSION_LABEL, prepared_state),
                ]
                mounted_provenance = [(label, state) for label, state in provenance_rows if state is not None]
                for index, (label, state) in enumerate(mounted_provenance):
                    detail_widgets.append(
                        TodoSessionRow(
                            todo=item,
                            slug=row.todo.slug,
                            label=label,
                            state=state,
                            is_last=not sorted_files and index == len(mounted_provenance) - 1,
                            tree_lines=detail_tree_lines,
                        )
                    )
                detail_widgets.extend(
                    TodoFileRow(
                        artifact_name=artifact_name,
                        filename=artifact_display_filename(artifact_name),
                        slug=row.todo.slug,
                        project_path=project_path,
                        todo_id=todo_id,
                        status=row.todo.status,
                        updated_at=item.artifact_updated_at.get(artifact_name),
                        is_last=(fi == len(sorted_files) - 1),
                        tree_lines=detail_tree_lines,
                    )
                    for fi, artifact_name in enumerate(sorted_files)
                )
                widgets_to_mount.extend(detail_widgets)
                self._detail_rows[todo_id] = detail_widgets
                expanded_file_rows.append(
                    (todo_row, [widget for widget in detail_widgets if isinstance(widget, TodoFileRow)])
                )

        # Group projects by computer, then pin the display order: local first,
        # then case-insensitive alphabetical. ``comp_name`` is the ``"local"``
        # sentinel for absent computers, which the key's three-encoding local
        # check sorts first.
        computer_order: list[str] = []
        computer_to_projects: dict[str, list[ProjectWithTodosDTO]] = {}
        for project in self._projects_with_todos:
            comp_name = project.computer or "local"
            if comp_name not in computer_to_projects:
                computer_order.append(comp_name)
                computer_to_projects[comp_name] = []
            computer_to_projects[comp_name].append(project)
        computer_order.sort(key=lambda name: _computer_order_key(name, config.computer.name))

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
                is_local=_is_local_name(comp_name, config.computer.name),
            )
            comp_display = ComputerDisplayInfo(
                computer=comp_info,
                session_count=comp_todo_count,
                recent_activity=False,
            )
            comp_collapsed = comp_name in self._collapsed_computers
            comp_header = ComputerHeader(data=comp_display, collapsed=comp_collapsed)
            widgets_to_mount.append(comp_header)
            self._nav_items.append(comp_header)
            if comp_collapsed:
                continue

            for project in projects_in_comp:
                proj_info = ProjectDTO(
                    computer=project.computer,
                    name=project.name,
                    path=project.path,
                    description=project.description,
                )
                proj_collapsed = project_collapse_key(project.computer, project.path) in self._collapsed_projects
                header = ProjectHeader(project=proj_info, session_count=0, collapsed=proj_collapsed)
                widgets_to_mount.append(header)
                self._nav_items.append(header)
                if proj_collapsed:
                    continue

                sections = project_sections[project_collapse_key(project.computer, project.path)]
                rendered_any = False

                active_rows = flatten(sections.active, force_root_branch=True)
                active_metrics = _section_metrics(active_rows, project.path, project.computer)
                for flat_row in active_rows:
                    _emit_row(flat_row, project.path, project.computer, active_metrics)
                    rendered_any = True

                # Delivered section — collapsible, rendered above icebox
                if project.path in self._delivered_projects:
                    delivered_rows = flatten(sections.delivered, force_root_branch=True)
                    if delivered_rows:
                        widgets_to_mount.append(DeliveredSeparator())
                        delivered_metrics = _section_metrics(delivered_rows, project.path, project.computer)
                        for flat_row in delivered_rows:
                            _emit_row(flat_row, project.path, project.computer, delivered_metrics)
                        rendered_any = True

                # Icebox section — collapsible
                if project.path in self._icebox_projects:
                    icebox_rows = flatten(sections.icebox, force_root_branch=True)
                    if icebox_rows:
                        widgets_to_mount.append(IceboxSeparator())
                        icebox_metrics = _section_metrics(icebox_rows, project.path, project.computer)
                        for flat_row in icebox_rows:
                            _emit_row(flat_row, project.path, project.computer, icebox_metrics)
                        rendered_any = True

                # Trashed section — collapsible
                if project.path in self._trashed_projects:
                    trashed_rows = flatten(sections.removed, force_root_branch=True)
                    if trashed_rows:
                        widgets_to_mount.append(TrashedSeparator())
                        trashed_metrics = _section_metrics(trashed_rows, project.path, project.computer)
                        for flat_row in trashed_rows:
                            _emit_row(flat_row, project.path, project.computer, trashed_metrics)
                        rendered_any = True

                if rendered_any:
                    widgets_to_mount.append(GroupSeparator(connector_col=ProjectHeader.CONNECTOR_COL))

        # Single batch mount - one layout reflow instead of N
        if widgets_to_mount:
            container.mount(*widgets_to_mount)

        # Insert file rows into nav_items at the correct positions
        for parent_row, file_ws in expanded_file_rows:
            row_idx = self._nav_items.index(parent_row)
            for i, fw in enumerate(file_ws):
                self._nav_items.insert(row_idx + 1 + i, fw)

        self._restore_cursor_to_highlighted_row()
        self._update_cursor_highlight()
        self._apply_human_filter()
        self._logger.trace(
            "[PERF] PrepView._rebuild done items=%d dt=%.3f", len(self._nav_items), _t.monotonic() - _rb0
        )

    def _mount_file_rows(self, container: VerticalScroll, todo_row: TodoRow) -> None:
        """Mount provenance metadata and navigable artifact rows for an expanded todo."""
        todo_id = self._require_row_todo_id(todo_row)
        if todo_id is None:
            return
        sorted_files = sorted(todo_row.todo.files)
        row_idx = self._nav_items.index(todo_row)
        # Detail tree_lines = parent's lines + parent's own branch continuation
        detail_tree_lines = list(todo_row._tree_lines) + [not todo_row.is_last]
        project_path = todo_row.todo.project_path or self._current_project_path()

        creator_state = resolve_creator_row_state(todo_row.todo.lineage, self._session_lookup)
        prepared_state = resolve_session_row_state(todo_row.todo.prepared_session_id, self._session_lookup)
        previous_widget: Widget = todo_row
        insert_at = row_idx + 1
        detail_rows: list[Widget] = []
        provenance_rows = [
            (_CREATOR_SESSION_LABEL, creator_state),
            (_PREPARED_SESSION_LABEL, prepared_state),
        ]
        mounted_provenance = [(label, state) for label, state in provenance_rows if state is not None]
        for index, (label, state) in enumerate(mounted_provenance):
            detail_row = TodoSessionRow(
                todo=todo_row.todo,
                slug=todo_row.slug,
                label=label,
                state=state,
                is_last=not sorted_files and index == len(mounted_provenance) - 1,
                tree_lines=detail_tree_lines,
            )
            container.mount(detail_row, after=previous_widget)
            previous_widget = detail_row
            detail_rows.append(detail_row)

        for i, artifact_name in enumerate(sorted_files):
            is_last = i == len(sorted_files) - 1
            file_row = TodoFileRow(
                artifact_name=artifact_name,
                filename=artifact_display_filename(artifact_name),
                slug=todo_row.slug,
                project_path=project_path,
                todo_id=todo_id,
                status=todo_row.todo.status,
                updated_at=todo_row.todo.artifact_updated_at.get(artifact_name),
                is_last=is_last,
                tree_lines=detail_tree_lines,
            )
            container.mount(file_row, after=previous_widget)
            self._nav_items.insert(insert_at + i, file_row)
            previous_widget = file_row
            detail_rows.append(file_row)
        self._detail_rows[todo_id] = detail_rows

    def _remove_file_rows(self, todo_row: TodoRow) -> None:
        """Remove provenance metadata and file rows belonging to a todo."""
        todo_id = todo_row.todo.todo_id
        if todo_id is None:
            return
        for widget in self._detail_rows.pop(todo_id, []):
            if isinstance(widget, TodoFileRow):
                self._nav_items.remove(widget)
            widget.remove()

    def _is_expanded(self, todo_id: str | None) -> bool:
        return todo_id is not None and todo_id in self._expanded_todos

    def _expand_todo(self, todo_row: TodoRow) -> None:
        """Expand a todo row - mount the creation-record detail row and file rows."""
        todo_id = self._require_row_todo_id(todo_row)
        if todo_id is None or todo_id in self._expanded_todos:
            return
        self._expanded_todos.add(todo_id)
        self.post_message(StateChanged())
        container = self.query_one("#preparation-scroll", VerticalScroll)
        self._mount_file_rows(container, todo_row)

    def _collapse_todo(self, todo_row: TodoRow) -> None:
        """Collapse a todo row - remove file rows."""
        todo_id = todo_row.todo.todo_id
        if todo_id is None or todo_id not in self._expanded_todos:
            return
        self._expanded_todos.discard(todo_id)
        self.post_message(StateChanged())
        self._remove_file_rows(todo_row)
        # Clamp cursor if it was on a removed file row
        if self.cursor_index >= len(self._nav_items):
            self.cursor_index = max(0, len(self._nav_items) - 1)
        self._update_cursor_highlight()

    def select_todo(self, slug: str) -> bool:
        """Move the cursor onto the todo with the given slug, if present.

        Used by the cross-view jump from a session's work slug. Returns True when
        a matching todo row was found and selected.
        """
        for i, widget in enumerate(self._nav_items):
            if isinstance(widget, TodoRow) and widget.slug == slug:
                self.cursor_index = i
                self._update_cursor_highlight()
                self.post_message(TodoSelected(slug))
                return True
        return False

    def set_human_filter(self, human_filter: str | None) -> None:
        """Set the shared human filter and apply it to the current rows."""
        self._human_filter = human_filter
        self._apply_human_filter()

    def _apply_human_filter(self) -> None:
        """Hide todo rows that do not belong to the active human filter.

        Each todo row also learns the active filter so the filtered person's chip
        renders inverted. Rows with no resolvable owner are hidden while a filter
        is active. Holder rows are exempt: a holder is a structural label with no
        owner of its own, so filtering it out would strip the tree parent from
        children that are themselves visible. The filter is inert in single-user
        mode (the ownership surface is suppressed), so every row stays visible
        regardless of any stale value.
        """
        active_filter = self._human_filter if ownership_surface_enabled() else None
        for widget in self._nav_items:
            if not isinstance(widget, TodoRow):
                continue
            widget._active_human_filter = active_filter
            if active_filter is None or widget.todo.is_holder:
                widget.display = True
            else:
                owner = principal_to_email(Lineage.root_of(widget.todo.lineage))
                widget.display = owner is not None and owner.lower() == active_filter
            widget.refresh()

    def _update_cursor_highlight(self) -> None:
        current = self._current_item()
        if current is not None:
            # A header or separator has no identity to restore, so it clears the
            # key rather than leaving the last durable row standing in for it.
            self._highlighted_row_key = _row_key(current)
        for i, widget in enumerate(self._nav_items):
            was_selected = widget.has_class("selected")
            is_selected = i == self.cursor_index
            widget.set_class(is_selected, "selected")
            if was_selected != is_selected:
                widget.refresh()

    def _restore_cursor_to_highlighted_row(self) -> None:
        """Put the cursor back on the row it was on, by identity not position.

        A rebuild reorders and replaces widgets, so an index means nothing
        across it. When the row is gone the index is clamped instead, which is
        the nearest surviving position.
        """
        if not self._nav_items:
            return
        if self._highlighted_row_key is not None:
            for index, widget in enumerate(self._nav_items):
                if _row_key(widget) == self._highlighted_row_key:
                    self.cursor_index = index
                    return
        if self.cursor_index >= len(self._nav_items):
            self.cursor_index = max(0, len(self._nav_items) - 1)

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
    def _artifact_doc_id(project_path: str, slug: str, artifact_name: str, *, todo_id: str | None = None) -> str:
        """Build a stable document id for a todo artifact."""
        return artifact_doc_id(project_path, slug, artifact_name, todo_id=todo_id)

    def _editor_command(
        self,
        *,
        project_path: str,
        slug: str,
        artifact_name: str,
        todo_id: str | None = None,
        status: TodoStatus | str | None = None,
        view: bool = False,
    ) -> str:
        """Build an editor command that materializes a DB artifact into a temp file."""
        args = [
            sys.executable,
            FLAG_MODULE,
            EDITOR_MODULE,
            FLAG_PROJECT_ROOT,
            project_path,
            FLAG_ARTIFACT_SLUG,
            slug,
            FLAG_ARTIFACT_NAME,
            artifact_name,
        ]
        if todo_id is not None:
            args.extend([FLAG_ARTIFACT_TODO_ID, todo_id])
        if view or status in RETAINED_TODO_STATUSES:
            args.append(FLAG_VIEW)

        if self.app and self.app.theme:
            args.extend([FLAG_THEME, self.app.theme])

        return shlex.join(args)

    def _find_parent_todo(self, file_row: TodoFileRow) -> TodoRow | None:
        """Find the TodoRow that owns a file row."""
        todo_id = file_row.todo_id
        idx = self._nav_items.index(file_row)
        for i in range(idx - 1, -1, -1):
            item = self._nav_items[i]
            if isinstance(item, TodoRow) and item.todo.todo_id == todo_id:
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

    def _resolve_cursor_context(self) -> _PreparationCursorContext | None:
        """Resolve the selected project's and todo's address from the cursor."""
        item = self._current_item()
        if item is None:
            return None

        if isinstance(item, ProjectHeader):
            return _PreparationCursorContext(item.project.computer or "local", item.project.path, None, None)

        if isinstance(item, TodoRow):
            slug = item.slug
            try:
                idx = self._nav_items.index(item)
            except ValueError:
                return None
            header = self._resolve_project_header_for_index(idx)
            if header:
                return _PreparationCursorContext(
                    header.project.computer or "local", header.project.path, slug, item.todo.todo_id
                )
            project_path = item.todo.project_path
            if project_path:
                return _PreparationCursorContext("local", project_path, slug, item.todo.todo_id)
            return None

        if isinstance(item, TodoFileRow) and item.slug:
            slug = item.slug
            try:
                idx = self._nav_items.index(item)
            except ValueError:
                return None
            header = self._resolve_project_header_for_index(idx)
            if header:
                return _PreparationCursorContext(
                    header.project.computer or "local", header.project.path, slug, item.todo_id
                )
            project_path = item.project_path
            if project_path:
                return _PreparationCursorContext("local", project_path, slug, item.todo_id)
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
        """Export the current expanded-todo, icebox, and trashed state for persistence."""
        return {
            "expanded_todos": sorted(self._expanded_todos),
            "collapsed_computers": sorted(self._collapsed_computers),
            "collapsed_projects": [list(key) for key in sorted(self._collapsed_projects)],
            "icebox_projects": sorted(self._icebox_projects),
            "delivered_projects": sorted(self._delivered_projects),
            "trashed_projects": sorted(self._trashed_projects),
            "highlighted_row_key": self._highlighted_row_key,
        }


# Legacy stub for tests
class PrepTodoDisplayInfo:
    """Minimal legacy todo display container kept for tests."""

    def __init__(self, todo: object, project_path: object, computer: object) -> None:
        self.todo = todo
        self.project_path = project_path
        self.computer = computer


class PrepTodoNode:
    """Legacy empty todo node stub retained for compatibility."""


class PrepComputerDisplayInfo:
    """Legacy empty computer display stub retained for compatibility."""


class PrepComputerNode:
    """Legacy empty computer node stub retained for compatibility."""


class PrepFileDisplayInfo:
    """Minimal legacy file display container kept for tests."""

    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class PrepFileNode:
    """Legacy empty file node stub retained for compatibility."""


class PrepProjectDisplayInfo:
    """Minimal legacy project display container kept for tests."""

    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class PrepProjectNode:
    """Legacy empty project node stub retained for compatibility."""
