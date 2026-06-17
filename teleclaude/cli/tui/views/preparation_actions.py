"""Action, check_action, and focus mixin for PreparationView."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, TypedDict, cast
from urllib.parse import quote

from teleclaude.api_models import TodoDumpRequest
from teleclaude.cli.tool_client import ToolAPIError, tool_api_request
from teleclaude.cli.tui.messages import DocEditRequest, DocPreviewRequest
from teleclaude.cli.tui.tree import project_collapse_key
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.utils.formatters import escape_markup
from teleclaude.cli.tui.views._footer_actions import refresh_footer_bindings, sync_default_footer_action
from teleclaude.cli.tui.views._project_actions import save_new_project
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.modals import (
    ConfirmModal,
    ContentInputModal,
    CreateSlugModal,
    NewProjectModal,
    NewProjectResult,
)
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
from teleclaude.cli.tui.widgets.todo_row import TodoRow
from teleclaude.config import config
from teleclaude.constants import ARTIFACT_INPUT, SlashCommand
from teleclaude.core.next_machine.lifecycle import (
    hold_control_available,
    is_ready_for_work,
    pending_approval_gate,
)
from teleclaude.types.todo_kind import ALL_DUMP_KINDS, TODO_KIND_BUG, TODO_KIND_FEATURE, TodoDumpKind

if TYPE_CHECKING:
    from teleclaude.api_models import ProjectWithTodosDTO

from teleclaude.cli.tui.messages import StateChanged


class _ApprovalGateState(TypedDict, total=False):
    kind: str | None
    lifecycle_phase: str | None


def _autostart_enabled_for_kind(kind: str | None) -> bool:
    if kind is None:
        return False
    return bool(getattr(config.workflow.autostart, kind, False))


def _approval_gate_pending(row: TodoRow) -> bool:
    if row.todo.status in {TodoStatus.ICEBOX, TodoStatus.DELIVERED, TodoStatus.REMOVED}:
        return False
    state: _ApprovalGateState = {
        "kind": row.todo.kind,
        "lifecycle_phase": row.todo.lifecycle_phase,
    }
    return pending_approval_gate(state) is not None


def _hold_control_available(row: TodoRow) -> bool:
    if row.todo.status in {TodoStatus.ICEBOX, TodoStatus.DELIVERED, TodoStatus.REMOVED}:
        return False
    return hold_control_available(
        {"lifecycle_phase": row.todo.lifecycle_phase, "hold": row.todo.hold},
        autostart_enabled=_autostart_enabled_for_kind(row.todo.kind),
    )


class PreparationViewActionsMixin:
    """Keyboard actions, check_action, watch_cursor_index, on_focus for PreparationView."""

    if TYPE_CHECKING:
        app: Any
        _projects_with_todos: list[ProjectWithTodosDTO]

    @staticmethod
    def _next_command(base: str, slug: str | None) -> str:
        """Build /next-* command with optional slug."""
        return f"/{base} {slug}" if slug else f"/{base}"

    def action_cursor_up(self) -> None:
        """Move the cursor to the previous preparation item."""
        if self._nav_items and self.cursor_index > 0:  # type: ignore[attr-defined]
            self.cursor_index -= 1  # type: ignore[attr-defined]
            self._update_cursor_highlight()  # type: ignore[attr-defined]
            if 0 <= self.cursor_index < len(self._nav_items):  # type: ignore[attr-defined]
                self._nav_items[self.cursor_index].scroll_visible()  # type: ignore[attr-defined]

    def action_cursor_down(self) -> None:
        """Move the cursor to the next preparation item."""
        if self._nav_items and self.cursor_index < len(self._nav_items) - 1:  # type: ignore[attr-defined]
            self.cursor_index += 1  # type: ignore[attr-defined]
            self._update_cursor_highlight()  # type: ignore[attr-defined]
            if 0 <= self.cursor_index < len(self._nav_items):  # type: ignore[attr-defined]
                self._nav_items[self.cursor_index].scroll_visible()  # type: ignore[attr-defined]

    def _current_computer_header(self) -> ComputerHeader | None:
        """Return the selected computer header, if the cursor is on one."""
        item = self._current_item()  # type: ignore[attr-defined]
        return item if isinstance(item, ComputerHeader) else None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Enable/hide actions based on current tree node type."""
        del parameters
        item = self._current_item()  # type: ignore[attr-defined]
        computer_only = {
            "new_todo",
            "new_bug",
            "remove_artifact",
            "activate",
            "preview_file",
            "prepare",
            "start_work",
            "freeze",
            "unfreeze",
            "approve_gate",
            "hold",
            "toggle_trashed",
            "reactivate_selected",
            "toggle_delivered",
            "toggle_icebox",
        }
        project_disallowed = {
            "remove_artifact",
            "activate",
            "preview_file",
            "new_project",
            "prepare",
            "start_work",
            "freeze",
            "unfreeze",
            "approve_gate",
            "hold",
        }
        file_disallowed = {
            "new_todo",
            "new_bug",
            "new_project",
            "freeze",
            "unfreeze",
            "approve_gate",
            "hold",
        }

        if isinstance(item, ComputerHeader):
            return action not in computer_only

        if isinstance(item, ProjectHeader):
            return action not in project_disallowed

        if isinstance(item, TodoRow):
            return self._check_todo_row_action(item, action)

        if isinstance(item, TodoFileRow):
            return action not in file_disallowed

        return True

    def _check_todo_row_action(self, item: TodoRow, action: str) -> bool:
        """Return whether ``action`` is enabled for a TodoRow node."""
        if action in {"preview_file", "new_project"}:
            return False
        if action == "unfreeze":
            return item.todo.status == TodoStatus.ICEBOX
        if action == "freeze":
            return item.todo.status != TodoStatus.ICEBOX
        if action == "hold":
            return _hold_control_available(item)
        if action == "approve_gate":
            return _approval_gate_pending(item)
        if action == "reactivate_selected":
            return item.todo.status == TodoStatus.REMOVED
        return True

    def watch_cursor_index(self, _index: int) -> None:
        """Refresh key bindings when node context changes."""
        if self.is_attached:  # type: ignore[attr-defined]
            self.app.refresh_bindings()  # type: ignore[attr-defined]
            self.call_after_refresh(self._sync_default_footer_action)  # type: ignore[attr-defined]

    def _default_footer_action(self) -> str | None:
        """Return the primary action for the selected node."""
        item = self._current_item()  # type: ignore[attr-defined]
        if isinstance(item, ComputerHeader):
            return "new_project"
        if isinstance(item, ProjectHeader):
            return "new_todo"
        if isinstance(item, TodoRow | TodoFileRow):
            return "activate"
        return None

    def _sync_default_footer_action(self) -> None:
        """Mark the active default action in Footer."""
        sync_default_footer_action(self, self._default_footer_action())

    def on_focus(self) -> None:
        """Sync default footer styling when the view receives focus."""
        refresh_footer_bindings(self, self._sync_default_footer_action)

    def action_expand(self) -> None:
        """Right: expand the selected computer, project, or todo."""
        item = self._current_item()  # type: ignore[attr-defined]
        if isinstance(item, ComputerHeader):
            name = item.data.computer.name
            if name in self._collapsed_computers:  # type: ignore[attr-defined]
                self._collapsed_computers.discard(name)  # type: ignore[attr-defined]
                self.post_message(StateChanged())  # type: ignore[attr-defined]
                self._rebuild()  # type: ignore[attr-defined]
            return
        if isinstance(item, ProjectHeader):
            key = project_collapse_key(item.project.computer, item.project.path)
            if key in self._collapsed_projects:  # type: ignore[attr-defined]
                self._collapsed_projects.discard(key)  # type: ignore[attr-defined]
                self.post_message(StateChanged())  # type: ignore[attr-defined]
                self._rebuild()  # type: ignore[attr-defined]
            return
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if row:
            self._expand_todo(row)  # type: ignore[attr-defined]

    def action_collapse(self) -> None:
        """Left: collapse the selected computer, project, todo, or jump from a file row."""
        item = self._current_item()  # type: ignore[attr-defined]
        if isinstance(item, ComputerHeader):
            name = item.data.computer.name
            if name not in self._collapsed_computers:  # type: ignore[attr-defined]
                self._collapsed_computers.add(name)  # type: ignore[attr-defined]
                self.post_message(StateChanged())  # type: ignore[attr-defined]
                self._rebuild()  # type: ignore[attr-defined]
            return
        if isinstance(item, ProjectHeader):
            key = project_collapse_key(item.project.computer, item.project.path)
            if key not in self._collapsed_projects:  # type: ignore[attr-defined]
                self._collapsed_projects.add(key)  # type: ignore[attr-defined]
                self.post_message(StateChanged())  # type: ignore[attr-defined]
                self._rebuild()  # type: ignore[attr-defined]
            return
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if row:
            self._collapse_todo(row)  # type: ignore[attr-defined]
            return
        file_row = self._current_file_row()  # type: ignore[attr-defined]
        if file_row:
            parent = self._find_parent_todo(file_row)  # type: ignore[attr-defined]
            if parent:
                self._collapse_todo(parent)  # type: ignore[attr-defined]
                # Move cursor to parent
                try:
                    self.cursor_index = self._nav_items.index(parent)  # type: ignore[attr-defined]
                except ValueError:
                    pass
                self._update_cursor_highlight()  # type: ignore[attr-defined]

    def action_activate(self) -> None:
        """Enter: toggle expand/collapse on todo, open editor on file."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if row:
            if self._is_expanded(row.slug):  # type: ignore[attr-defined]
                self._collapse_todo(row)  # type: ignore[attr-defined]
            else:
                self._expand_todo(row)  # type: ignore[attr-defined]
            return
        file_row = self._current_file_row()  # type: ignore[attr-defined]
        if file_row:
            self.post_message(  # type: ignore[attr-defined]
                DocEditRequest(
                    doc_id=self._artifact_doc_id(  # type: ignore[attr-defined]
                        file_row.project_path,
                        file_row.slug,
                        file_row.artifact_name,
                    ),
                    command=self._editor_command(  # type: ignore[attr-defined]
                        project_path=file_row.project_path,
                        slug=file_row.slug,
                        artifact_name=file_row.artifact_name,
                    ),
                    title=f"Editing: {file_row.filename}",
                )
            )

    def action_expand_all(self) -> None:
        """Expand every todo row in the current list."""
        for widget in list(self._nav_items):  # type: ignore[attr-defined]
            if isinstance(widget, TodoRow) and not self._is_expanded(widget.slug):  # type: ignore[attr-defined]
                self._expand_todo(widget)  # type: ignore[attr-defined]

    def action_collapse_all(self) -> None:
        """Collapse every expanded todo row in the current list."""
        for widget in list(self._nav_items):  # type: ignore[attr-defined]
            if isinstance(widget, TodoRow) and self._is_expanded(widget.slug):  # type: ignore[attr-defined]
                self._collapse_todo(widget)  # type: ignore[attr-defined]

    def action_expand_structure(self) -> None:
        """+ : expand every computer and project (structural level)."""
        if not self._collapsed_computers and not self._collapsed_projects:  # type: ignore[attr-defined]
            return
        self._collapsed_computers.clear()  # type: ignore[attr-defined]
        self._collapsed_projects.clear()  # type: ignore[attr-defined]
        self.post_message(StateChanged())  # type: ignore[attr-defined]
        self._rebuild()  # type: ignore[attr-defined]

    def action_collapse_structure(self) -> None:
        """_ : collapse every computer and project (structural level)."""
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        target_computer = context[0] if context else None
        self._collapsed_computers = {p.computer or "local" for p in self._projects_with_todos}  # type: ignore[attr-defined]
        self._collapsed_projects = {  # type: ignore[attr-defined]
            project_collapse_key(p.computer, p.path)
            for p in self._projects_with_todos  # type: ignore[attr-defined]
        }
        self.post_message(StateChanged())  # type: ignore[attr-defined]
        self._rebuild()  # type: ignore[attr-defined]
        if target_computer is not None:
            for i, widget in enumerate(self._nav_items):  # type: ignore[attr-defined]
                if isinstance(widget, ComputerHeader) and widget.data.computer.name == target_computer:
                    self.cursor_index = i  # type: ignore[attr-defined]
                    self._update_cursor_highlight()  # type: ignore[attr-defined]
                    self._nav_items[i].scroll_visible()  # type: ignore[attr-defined]
                    break

    def action_preview_file(self) -> None:
        """Space: preview the current file in view mode (no focus)."""
        file_row = self._current_file_row()  # type: ignore[attr-defined]
        if file_row:
            self.post_message(  # type: ignore[attr-defined]
                DocPreviewRequest(
                    doc_id=self._artifact_doc_id(  # type: ignore[attr-defined]
                        file_row.project_path,
                        file_row.slug,
                        file_row.artifact_name,
                    ),
                    command=self._editor_command(  # type: ignore[attr-defined]
                        project_path=file_row.project_path,
                        slug=file_row.slug,
                        artifact_name=file_row.artifact_name,
                        view=True,
                    ),
                    title=file_row.filename,
                )
            )

    def _current_project_path(self) -> str:
        """Return the active project path from known rows or cwd."""
        for path in self._slug_to_project_path.values():  # type: ignore[attr-defined]
            return path
        return os.getcwd()

    def _create_item(self, slug: str, *, kind: str | None) -> None:
        """Create a todo or bug via the daemon API after content modal confirmation."""
        project_root = self._current_project_path()

        def _on_content(content: str | None) -> None:
            if not content or not content.strip():
                return

            request = TodoDumpRequest(
                slug=slug,
                content=content.strip(),
                kind=cast(TodoDumpKind, kind) if kind in ALL_DUMP_KINDS else None,
                cwd=project_root,
            )

            try:
                result = tool_api_request(
                    "POST", "/todos/dump", json_body=request.model_dump(mode="json"), timeout=10.0
                )
            except Exception as exc:
                self.app.notify(escape_markup(str(exc)), severity="error")  # type: ignore[attr-defined]
                return

            if isinstance(result, dict) and result.get("status") == "ok":
                self.app.notify(f"Created {slug}")  # type: ignore[attr-defined]
            elif isinstance(result, dict) and result.get("detail"):
                self.app.notify(escape_markup(str(result["detail"])), severity="error")  # type: ignore[attr-defined]
            else:
                self.app.notify(escape_markup(f"Unexpected response: {result}"), severity="error")  # type: ignore[attr-defined]

        self.app.push_screen(  # type: ignore[attr-defined]
            ContentInputModal(title=f"New {'Bug' if kind == 'bug' else 'Todo'}"),
            callback=_on_content,
        )

    def action_new_project(self) -> None:
        """n on computer header: open New Project modal."""
        item = self._current_item()  # type: ignore[attr-defined]
        if not isinstance(item, ComputerHeader):
            return

        comp_name = item.data.computer.name
        existing_projects = [  # type: ignore[attr-defined]
            p for p in self._projects_with_todos if (p.computer or "local") == comp_name
        ]
        existing_names = {p.name for p in existing_projects}
        existing_paths = {p.path for p in existing_projects}

        def on_result(result: NewProjectResult | None) -> None:
            if not result:
                return
            save_new_project(self.app, result)  # type: ignore[attr-defined]

        self.app.push_screen(  # type: ignore[attr-defined]
            NewProjectModal(existing_names=existing_names, existing_paths=existing_paths),
            on_result,
        )

    def action_new_todo(self) -> None:
        """n: create a new todo via modal."""

        def _on_result(slug: str | None) -> None:
            if slug:
                self._create_item(slug, kind=None)

        self.app.push_screen(  # type: ignore[attr-defined]
            CreateSlugModal(title="New Todo"),
            callback=_on_result,
        )

    def action_new_bug(self) -> None:
        """b: create a new bug via modal."""

        def _on_result(slug: str | None) -> None:
            if slug:
                self._create_item(slug, kind=TODO_KIND_BUG)

        self.app.push_screen(  # type: ignore[attr-defined]
            CreateSlugModal(title="New Bug", placeholder="my-new-bug"),
            callback=_on_result,
        )

    def action_remove_artifact(self) -> None:
        """R: on an artifact row remove that artifact (≠ 'input'); on a todo row remove the todo."""
        file_row = self._current_file_row()  # type: ignore[attr-defined]
        if file_row is not None:
            artifact_name = file_row.artifact_name
            slug = file_row.slug
            if artifact_name == ARTIFACT_INPUT:
                self.app.notify("The 'input' artifact cannot be removed.", severity="warning")  # type: ignore[attr-defined]
                return
            project_path = self._slug_to_project_path.get(slug, "") or (file_row.project_path or "")  # type: ignore[attr-defined]
            if not project_path:
                return

            def _on_confirm_artifact(confirmed: bool | None) -> None:
                if not confirmed:
                    return
                try:
                    result = tool_api_request(
                        "DELETE",
                        f"/todos/artifacts/{quote(slug)}/{quote(artifact_name)}",
                        params={"cwd": project_path},
                        timeout=10.0,
                    )
                except ToolAPIError as exc:
                    self.app.notify(escape_markup(str(exc)), severity="error")  # type: ignore[attr-defined]
                    return
                if isinstance(result, dict) and result.get("status") == "ok":
                    self.app.notify(f"Removed artifact '{artifact_name}' from {slug}")  # type: ignore[attr-defined]
                    self.app._refresh_data()  # type: ignore[attr-defined]
                elif isinstance(result, dict) and result.get("detail"):
                    self.app.notify(escape_markup(str(result["detail"])), severity="error")  # type: ignore[attr-defined]
                else:
                    self.app.notify(escape_markup(f"Unexpected response: {result}"), severity="error")  # type: ignore[attr-defined]

            self.app.push_screen(  # type: ignore[attr-defined]
                ConfirmModal(
                    title="Remove Artifact",
                    message=f"Remove artifact '{artifact_name}' from '{slug}'?\n\nThis deletes its version history and cannot be undone.",
                ),
                _on_confirm_artifact,
            )
            return

        # Todo row → remove the whole todo (original behavior).
        row = self._current_todo_row()  # type: ignore[attr-defined]
        slug = row.slug if row else None
        if not slug:
            return
        project_path = self._slug_to_project_path.get(slug, "")  # type: ignore[attr-defined]
        if not project_path:
            return

        def _on_confirm_todo(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                result = tool_api_request(
                    "POST",
                    "/todos/remove",
                    json_body={"slug": slug, "cwd": project_path},
                    timeout=10.0,
                )
            except ToolAPIError as exc:
                self.app.notify(escape_markup(str(exc)), severity="error")  # type: ignore[attr-defined]
                return
            if isinstance(result, dict) and result.get("operation_id"):
                self.app.notify(f"Removing {slug}...")  # type: ignore[attr-defined]
            elif isinstance(result, dict) and result.get("detail"):
                self.app.notify(escape_markup(str(result["detail"])), severity="error")  # type: ignore[attr-defined]
            else:
                self.app.notify(escape_markup(f"Unexpected response: {result}"), severity="error")  # type: ignore[attr-defined]

        self.app.push_screen(  # type: ignore[attr-defined]
            ConfirmModal(
                title="Remove Todo",
                message=f"Remove todo '{slug}'?\n\nThis action cannot be undone.",
            ),
            _on_confirm_todo,
        )

    def action_prepare(self) -> None:
        """p: open session modal prefilled with /next-prepare [slug]."""
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        if not context:
            return
        computer, project_path, slug = context
        self._open_session_modal(  # type: ignore[attr-defined]
            computer=computer,
            project_path=project_path,
            default_message=self._next_command(SlashCommand.NEXT_PREPARE.value, slug),
            title=f"Prepare: {slug}" if slug else "Prepare",
        )

    def action_start_work(self) -> None:
        """s: open session modal prefilled with /next-work [slug].

        Gated on canonical lifecycle readiness when a specific todo is selected.
        """
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        if not context:
            return
        computer, project_path, slug = context

        if slug:
            todo_row = self._resolve_todo_for_cursor()  # type: ignore[attr-defined]
            if not todo_row:
                return
            kind = todo_row.todo.kind or TODO_KIND_FEATURE
            ready, reason = is_ready_for_work(kind=kind, lifecycle_phase=todo_row.todo.lifecycle_phase)
            if not ready:
                self.app.notify(
                    f"Todo is not ready to start work: {reason}",
                    severity="warning",
                )  # type: ignore[attr-defined]
                return

        self._open_session_modal(  # type: ignore[attr-defined]
            computer=computer,
            project_path=project_path,
            default_message=self._next_command(SlashCommand.NEXT_WORK.value, slug),
            title=f"Start Work: {slug}" if slug else "Start Work",
        )

    def action_freeze(self) -> None:
        """f: freeze a todo to the icebox."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        slug = row.slug if row else None
        if not slug:
            return

        project_path = self._slug_to_project_path.get(slug, "")  # type: ignore[attr-defined]
        if not project_path:
            return

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                result = tool_api_request(
                    "POST",
                    f"/todos/freeze/{slug}",
                    json_body={"cwd": project_path},
                    timeout=10.0,
                )
                if isinstance(result, dict) and result.get("status") == "ok":
                    self.app.notify(f"Frozen '{slug}' to icebox")  # type: ignore[attr-defined]
                    self.app._refresh_data()  # type: ignore[attr-defined]
                elif isinstance(result, dict) and result.get("detail"):
                    self.app.notify(escape_markup(str(result["detail"])), severity="error")  # type: ignore[attr-defined]
            except Exception as exc:
                self.app.notify(escape_markup(str(exc)), severity="error")  # type: ignore[attr-defined]

        self.app.push_screen(  # type: ignore[attr-defined]
            ConfirmModal(
                title="Freeze Todo",
                message=f"Freeze '{slug}' to icebox?",
            ),
            _on_confirm,
        )

    def action_toggle_icebox(self) -> None:
        """i: toggle icebox visibility, scoped to computer or project."""
        item = self._current_item()  # type: ignore[attr-defined]
        if isinstance(item, ComputerHeader):
            comp_name = item.data.computer.name
            project_paths = [
                p.path
                for p in self._projects_with_todos  # type: ignore[attr-defined]
                if (p.computer or "local") == comp_name
            ]
            # Toggle: if all are visible, hide all; otherwise show all
            all_visible = all(p in self._icebox_projects for p in project_paths)  # type: ignore[attr-defined]
            for path in project_paths:
                if all_visible:
                    self._icebox_projects.discard(path)  # type: ignore[attr-defined]
                else:
                    self._icebox_projects.add(path)  # type: ignore[attr-defined]
        else:
            # Resolve project path from cursor context
            context = self._resolve_cursor_context()  # type: ignore[attr-defined]
            if not context:
                return
            _, project_path, _ = context
            if project_path in self._icebox_projects:  # type: ignore[attr-defined]
                self._icebox_projects.discard(project_path)  # type: ignore[attr-defined]
            else:
                self._icebox_projects.add(project_path)  # type: ignore[attr-defined]

        self.post_message(StateChanged())  # type: ignore[attr-defined]
        self._rebuild()  # type: ignore[attr-defined]

    def action_toggle_delivered(self) -> None:
        """d: toggle the delivered section visibility, scoped to computer or project."""
        item = self._current_item()  # type: ignore[attr-defined]
        if isinstance(item, ComputerHeader):
            comp_name = item.data.computer.name
            project_paths = [
                p.path
                for p in self._projects_with_todos  # type: ignore[attr-defined]
                if (p.computer or "local") == comp_name
            ]
            # Toggle: if all are visible, hide all; otherwise show all
            all_visible = all(p in self._delivered_projects for p in project_paths)  # type: ignore[attr-defined]
            for path in project_paths:
                if all_visible:
                    self._delivered_projects.discard(path)  # type: ignore[attr-defined]
                else:
                    self._delivered_projects.add(path)  # type: ignore[attr-defined]
        else:
            context = self._resolve_cursor_context()  # type: ignore[attr-defined]
            if not context:
                return
            _, project_path, _ = context
            if project_path in self._delivered_projects:  # type: ignore[attr-defined]
                self._delivered_projects.discard(project_path)  # type: ignore[attr-defined]
            else:
                self._delivered_projects.add(project_path)  # type: ignore[attr-defined]

        self.post_message(StateChanged())  # type: ignore[attr-defined]
        self._rebuild()  # type: ignore[attr-defined]

    def action_unfreeze(self) -> None:
        """u: unfreeze an icebox todo back to the active todo list."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if not row or row.todo.status != TodoStatus.ICEBOX:
            return

        slug = row.slug
        project_path = self._slug_to_project_path.get(slug, "")  # type: ignore[attr-defined]
        if not project_path:
            return

        try:
            result = tool_api_request(
                "POST",
                f"/todos/unfreeze/{slug}",
                json_body={"cwd": project_path},
                timeout=10.0,
            )
            if isinstance(result, dict) and result.get("status") == "ok":
                self.app.notify(f"Unfrozen '{slug}' to todo list")  # type: ignore[attr-defined]
                self.app._refresh_data()  # type: ignore[attr-defined]
            elif isinstance(result, dict) and result.get("detail"):
                self.app.notify(escape_markup(str(result["detail"])), severity="error")  # type: ignore[attr-defined]
        except Exception as exc:
            self.app.notify(escape_markup(str(exc)), severity="error")  # type: ignore[attr-defined]

    def action_hold(self) -> None:
        """h: engage the automatic-dispatch hold brake (one-way; START proceeds)."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if not row:
            return

        if not _hold_control_available(row):
            self.app.notify("No hold control is available for this todo", severity="warning")  # type: ignore[attr-defined]
            return

        slug = row.slug
        project_path = self._slug_to_project_path.get(slug, "")  # type: ignore[attr-defined]
        if not project_path:
            return

        try:
            result = tool_api_request(
                "POST",
                "/todos/update",
                json_body={"slug": slug, "cwd": project_path, "hold": True},
                timeout=10.0,
            )
            if isinstance(result, dict) and result.get("status") == "ok":
                self.app.notify(f"Held '{slug}'")  # type: ignore[attr-defined]
                self.app._refresh_data()  # type: ignore[attr-defined]
            elif isinstance(result, dict) and result.get("detail"):
                self.app.notify(escape_markup(str(result["detail"])), severity="error")  # type: ignore[attr-defined]
            else:
                self.app.notify(escape_markup(f"Unexpected response: {result}"), severity="error")  # type: ignore[attr-defined]
        except Exception as exc:
            self.app.notify(escape_markup(str(exc)), severity="error")  # type: ignore[attr-defined]

    def action_approve_gate(self) -> None:
        """A: approve the selected todo's current human gate."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if not row:
            return
        if not _approval_gate_pending(row):
            self.app.notify("No approval gate is pending for this todo", severity="warning")  # type: ignore[attr-defined]
            return

        slug = row.slug
        project_path = self._slug_to_project_path.get(slug, "")  # type: ignore[attr-defined]
        if not project_path:
            return

        try:
            result = tool_api_request(
                "POST",
                "/todos/approve",
                json_body={"slug": slug, "cwd": project_path},
                timeout=10.0,
            )
            if isinstance(result, dict) and result.get("status") == "ok":
                self.app.notify(f"Approved '{slug}'")  # type: ignore[attr-defined]
                self.app._refresh_data()  # type: ignore[attr-defined]
            elif isinstance(result, dict) and result.get("detail"):
                self.app.notify(escape_markup(str(result["detail"])), severity="error")  # type: ignore[attr-defined]
            else:
                self.app.notify(escape_markup(f"Unexpected response: {result}"), severity="error")  # type: ignore[attr-defined]
        except Exception as exc:
            self.app.notify(escape_markup(str(exc)), severity="error")  # type: ignore[attr-defined]

    def action_toggle_trashed(self) -> None:
        """x: toggle the trashed section visibility, scoped to computer or project."""
        item = self._current_item()  # type: ignore[attr-defined]
        if isinstance(item, ComputerHeader):
            comp_name = item.data.computer.name
            project_paths = [
                p.path
                for p in self._projects_with_todos  # type: ignore[attr-defined]
                if (p.computer or "local") == comp_name
            ]
            # Toggle: if all are visible, hide all; otherwise show all
            all_visible = all(p in self._trashed_projects for p in project_paths)  # type: ignore[attr-defined]
            for path in project_paths:
                if all_visible:
                    self._trashed_projects.discard(path)  # type: ignore[attr-defined]
                else:
                    self._trashed_projects.add(path)  # type: ignore[attr-defined]
        else:
            context = self._resolve_cursor_context()  # type: ignore[attr-defined]
            if not context:
                return
            _, project_path, _ = context
            if project_path in self._trashed_projects:  # type: ignore[attr-defined]
                self._trashed_projects.discard(project_path)  # type: ignore[attr-defined]
            else:
                self._trashed_projects.add(project_path)  # type: ignore[attr-defined]

        self.post_message(StateChanged())  # type: ignore[attr-defined]
        self._rebuild()  # type: ignore[attr-defined]

    def action_reactivate_selected(self) -> None:
        """U: restore a trashed todo addressed by row-id."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if not row:
            return

        if row.todo.status != TodoStatus.REMOVED:
            self.app.notify("Reactivate only applies to trashed entries")  # type: ignore[attr-defined]
            return

        roadmap_id = row.todo.roadmap_id
        if not roadmap_id:
            self.app.notify("row missing durable id; refresh the roadmap pane", severity="warning")  # type: ignore[attr-defined]
            return

        slug = row.slug
        project_path = self._slug_to_project_path.get(slug, "")  # type: ignore[attr-defined]
        if not project_path:
            return

        try:
            result = tool_api_request(
                "POST",
                f"/todos/by-id/{roadmap_id}/reactivate",
                json_body={"cwd": project_path},
                timeout=10.0,
            )
            if isinstance(result, dict) and result.get("status") == "ok":
                self.app.notify(f"Restored '{slug}' to roadmap")  # type: ignore[attr-defined]
                # Rely on _on_mutation("todo_updated") to refresh via websocket,
                # but call refresh_data to be sure if needed.
                self.app._refresh_data()  # type: ignore[attr-defined]
            elif isinstance(result, dict) and result.get("detail"):
                self.app.notify(escape_markup(str(result["detail"])), severity="error")  # type: ignore[attr-defined]
        except Exception as exc:
            self.app.notify(escape_markup(str(exc)), severity="error")  # type: ignore[attr-defined]
