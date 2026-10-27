"""Action, check_action, and focus mixin for PreparationView."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, TypedDict
from urllib.parse import quote

from instrukt_ai_logging import get_logger
from textual import work

from teleclaude.api_models import TodoDumpRequest
from teleclaude.caller_identity import ProjectPath, RoleTarget
from teleclaude.cli.clearance import ClearanceScope
from teleclaude.cli.tool_client import ToolAPIError, ToolQueryParams, tool_api_request
from teleclaude.cli.tui.local_computer import remote_computer
from teleclaude.cli.tui.messages import DocEditRequest, DocPreviewRequest, StateChanged
from teleclaude.cli.tui.tree import project_collapse_key
from teleclaude.cli.tui.views._footer_actions import refresh_footer_bindings, sync_default_footer_action
from teleclaude.cli.tui.views._project_actions import start_new_project_save
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.modals import (
    ConfirmModal,
    ContentInputModal,
    CreateSlugModal,
    CreateSlugResult,
    NewProjectModal,
    NewProjectResult,
)
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
from teleclaude.cli.tui.widgets.todo_row import TodoRow
from teleclaude.constants import ARTIFACT_INPUT, TodoStatus
from teleclaude.core.next_machine.lifecycle import (
    ApprovalGate,
    pending_approval_gate,
)
from teleclaude.core.operations.service import TERMINAL_OPERATION_STATES
from teleclaude.project_root import resolve_invocation_roots
from teleclaude.types.todo_kind import (
    TODO_KIND_BUG,
    TodoDumpKind,
)

logger = get_logger(__name__)

if TYPE_CHECKING:
    from teleclaude.api_models import ProjectWithTodosDTO

# Lifecycle-operation follow-through: how long to poll before surfacing an
# unknown outcome, and the fallback delay between polls when the response
# carries no positive poll_after_ms.
_LIFECYCLE_POLL_BUDGET_S = 60.0
_LIFECYCLE_POLL_DEFAULT_DELAY_S = 0.25
_UNRESOLVED_TARGET_EVENT = "preparation_action_target_unresolved"
_NEW_BUG_MODAL_TITLE = "New Bug"
_NEW_BUG_SLUG_PLACEHOLDER = "my-new-bug"
RETAINED_TODO_STATUSES: frozenset[TodoStatus] = frozenset({TodoStatus.REMOVED, TodoStatus.DELIVERED})
_ROW_ACTION_FAILURE_EVENT = "tui.preparation_row_action_failed"
_ROW_ACTION_RESOLVE_IDENTITY = "resolve_todo_identity"
_ROW_ACTION_POST = "POST"
_ROW_ACTION_DELETE = "DELETE"
_TODO_BY_ID_ACTION_PATH_TEMPLATE = "/todos/by-id/{todo_id}/{action}"
_TODO_BY_ID_ARTIFACT_PATH_TEMPLATE = "/todos/by-id/{todo_id}/artifacts/{name}"
_TODO_PREPARE_PATH = "/todos/prepare"
_TODO_DUMP_PATH = "/todos/dump"
_JSON_DUMP_MODE = "json"
_BUGS_REPORT_VERB = "bugs report"
_TODO_CREATE_VERB = "todo create"
_WORK_FEEDBACK_ATTRIBUTE = "work_feedback"
_FILING_WORKER_GROUP = "todo-filing"
_FILING_STARTED_TEMPLATE = "Filing {slug}…"
_FILING_CREATED_TEMPLATE = "Created {slug}"
_FILING_FAILED_TEMPLATE = "Filing {slug} failed: {error}"
_NOTIFY_SEVERITY_ERROR = "error"
_TODO_WORK_PATH = "/todos/work"
_REMOVE_ARTIFACT_SUCCESS_TEMPLATE = "Removed artifact '{artifact_name}' from {slug}"
_INPUT_ARTIFACT_REMOVAL_WARNING = "The 'input' artifact cannot be removed."
_REMOVE_ARTIFACT_MODAL_TITLE = "Remove Artifact"
_REMOVE_ARTIFACT_CONFIRM_TEMPLATE = (
    "Remove artifact '{artifact_name}' from '{slug}'?\n\nThis deletes its version history and cannot be undone."
)
_REMOVE_TODO_MODAL_TITLE = "Remove Todo"
_REMOVE_TODO_CONFIRM_TEMPLATE = "Remove todo '{slug}'?\n\nThis action cannot be undone."
_FREEZE_SUCCESS_TEMPLATE = "Frozen '{slug}' to icebox"
_UNFREEZE_SUCCESS_TEMPLATE = "Unfrozen '{slug}' to todo list"
_APPROVE_SUCCESS_TEMPLATE = "Approved '{slug}'"
_VIEWING_FILE_TITLE_TEMPLATE = "Viewing: {filename}"
_EDITING_FILE_TITLE_TEMPLATE = "Editing: {filename}"
_PREPARING_LABEL_TEMPLATE = "Preparing {slug}"
_STARTING_WORK_LABEL_TEMPLATE = "Starting work {slug}"
_REMOVING_TODO_LABEL_TEMPLATE = "Removing {slug}"
_CWD_BODY_KEY = "cwd"
_COMPUTER_PARAM = "computer"
_REASON_BODY_KEY = "reason"
_STAMP_TYPE_BODY_KEY = "stamp_type"

# Wire contract for GET /operations/{operation_id}, per _serialize_operation
# (teleclaude/core/operations/service.py) — the serialized field names, not
# the model column names, and the values the follow-through worker branches on.
_HTTP_METHOD_GET = "GET"
_OPERATION_READ_VERB = "operations get"
_OPERATION_STATUS_PATH_TEMPLATE = "/operations/{operation_id}"
_OPERATION_RESPONSE_KEY_OPERATION_ID = "operation_id"
_OPERATION_RESPONSE_KEY_STATE = "state"
_OPERATION_RESPONSE_KEY_ERROR = "error"
_OPERATION_RESPONSE_KEY_WORK_FEEDBACK = "work_feedback"
_OPERATION_RESPONSE_KEY_RECOVERY_COMMAND = "recovery_command"
_OPERATION_RESPONSE_KEY_POLL_AFTER_MS = "poll_after_ms"
_OPERATION_STATE_COMPLETED = "completed"
_NOTIFY_SEVERITY_WARNING = "warning"
_RECOVERY_COMMAND_TEMPLATE = "telec operations get {operation_id}"
_OUTCOME_UNKNOWN_LOG = "TUI could not establish the operation outcome before its observation bound"
_OPERATION_OUTCOME_LOG = "TUI observed an operation without declared work feedback"
_WARNING_RESPONSE_KEY = "warnings"
_RESPONSE_KEY_STATUS = "status"
_RESPONSE_STATUS_OK = "ok"
_RESPONSE_KEY_DETAIL = "detail"
_HOLD_MODAL_TITLE = "Hold todo"
_HOLD_MODAL_PROMPT = "Why hold this todo?"
_HOLD_MODAL_PLACEHOLDER = "Enter a reason..."
_HOLD_MODAL_SUBMIT_LABEL = "Hold"
_NO_HOLD_CONTROL_MESSAGE = "No hold control is available for this todo"
_HOLD_SUCCESS_MESSAGE_TEMPLATE = "Held '{slug}'"
_RELEASE_HOLD_SUCCESS_MESSAGE_TEMPLATE = "Released hold on '{slug}'"
_REMOTE_PROJECT_NOTICE = "Add a project on its own computer."


def _with_computer(params: ToolQueryParams | None, computer: str | None) -> ToolQueryParams | None:
    """The query parameters addressed to the row's computer when that is another computer."""
    owner = remote_computer(computer)
    if owner is None:
        return params
    return {**(dict(params) if isinstance(params, Mapping) else {}), _COMPUTER_PARAM: owner}


class PreparationAction(StrEnum):
    """Closed vocabulary for Preparation view actions added after the legacy bindings."""

    FLASH_DEPENDENCIES = "flash_dependencies"
    PREPARE = "prepare"
    START_WORK = "start_work"
    FREEZE = "freeze"
    UNFREEZE = "unfreeze"
    HOLD = "hold"
    APPROVE_GATE = "approve_gate"
    REMOVE_ARTIFACT = "remove_artifact"
    REACTIVATE_SELECTED = "reactivate_selected"
    ACTIVATE = "activate"
    PREVIEW_FILE = "preview_file"


class _IdentityTodoRoute(StrEnum):
    """Closed identity-route path vocabulary consumed by the Preparation view."""

    PREPARE = "prepare"
    WORK = "work"
    REMOVE = "remove"
    FREEZE = "freeze"
    UNFREEZE = "unfreeze"
    HOLD = "hold"
    RELEASE = "release"
    STAMP = "stamp"


class _RetainedRowActions(NamedTuple):
    todo_row: frozenset[PreparationAction]
    file_row: frozenset[PreparationAction]


_RETAINED_TODO_ACTIONS: dict[TodoStatus, _RetainedRowActions] = {
    TodoStatus.REMOVED: _RetainedRowActions(
        todo_row=frozenset({PreparationAction.ACTIVATE, PreparationAction.REACTIVATE_SELECTED}),
        file_row=frozenset({PreparationAction.ACTIVATE, PreparationAction.PREVIEW_FILE}),
    ),
    TodoStatus.DELIVERED: _RetainedRowActions(
        todo_row=frozenset({PreparationAction.ACTIVATE}),
        file_row=frozenset({PreparationAction.ACTIVATE, PreparationAction.PREVIEW_FILE}),
    ),
}
_ROW_ADDRESSED_ACTIONS: frozenset[PreparationAction] = frozenset(
    {
        PreparationAction.PREPARE,
        PreparationAction.START_WORK,
        PreparationAction.FREEZE,
        PreparationAction.UNFREEZE,
        PreparationAction.HOLD,
        PreparationAction.APPROVE_GATE,
        PreparationAction.REMOVE_ARTIFACT,
        PreparationAction.REACTIVATE_SELECTED,
        PreparationAction.ACTIVATE,
        PreparationAction.PREVIEW_FILE,
    }
)
_ACTION_CLEARANCE_VERBS: dict[PreparationAction, str] = {
    PreparationAction.PREPARE: "todo prepare",
    PreparationAction.START_WORK: "todo work",
    PreparationAction.FREEZE: "todo freeze",
    PreparationAction.UNFREEZE: "todo unfreeze",
    PreparationAction.HOLD: "todo update",
    PreparationAction.APPROVE_GATE: "todo stamp",
    PreparationAction.REMOVE_ARTIFACT: "todo artifacts remove",
    PreparationAction.REACTIVATE_SELECTED: "todo reactivate",
}


class _ApprovalGateState(TypedDict, total=False):
    kind: str | None
    lifecycle_phase: str | None


_APPROVAL_GATE_STAMP_TYPE: dict[ApprovalGate, str] = {
    ApprovalGate.PRD: "prd_approved",
    ApprovalGate.CREATIVE_DESIGN_SPEC: "creative_design_spec_confirmed",
    ApprovalGate.CREATIVE_ART: "creative_art_approved",
    ApprovalGate.CREATIVE_VISUALS: "creative_visuals_approved",
}


def _pending_gate_stamp_type(row: TodoRow) -> str | None:
    """Return the explicit stamp type for the row's pending human gate, if any."""
    if row.todo.status in {TodoStatus.ICEBOX, TodoStatus.DELIVERED, TodoStatus.REMOVED}:
        return None
    if _task_authorization_pending(row):
        return "task_approved"
    state: _ApprovalGateState = {
        "kind": row.todo.kind,
        "lifecycle_phase": row.todo.lifecycle_phase,
    }
    gate = pending_approval_gate(state)
    return _APPROVAL_GATE_STAMP_TYPE.get(gate) if gate is not None else None


def _task_authorization_pending(row: TodoRow) -> bool:
    if row.todo.kind != "task" or row.todo.lifecycle_phase != "prepared":
        return False
    if not row.todo.task_plan_digest:
        return False
    return row.todo.task_approved_digest != row.todo.task_plan_digest


def _approval_gate_pending(row: TodoRow) -> bool:
    return _pending_gate_stamp_type(row) is not None


def _hold_control_available(row: TodoRow) -> bool:
    if row.todo.status in {TodoStatus.ICEBOX, TodoStatus.DELIVERED, TodoStatus.HOLDER, TodoStatus.REMOVED}:
        return False
    # Active todos can be held or released through the same contextual control.
    return True


class PreparationViewActionsMixin:
    """Keyboard actions, check_action, watch_cursor_index, on_focus for PreparationView."""

    def _report_unresolved_target(self, action: PreparationAction, slug: str | None) -> None:
        """Log a row action whose project target cannot be resolved."""
        item = self._current_item()  # type: ignore[attr-defined]
        logger.error(
            _UNRESOLVED_TARGET_EVENT,
            action=action.value,
            slug=slug,
            item_type=type(item).__name__ if item is not None else None,
        )

    def _require_row_todo_id(self, row: TodoRow) -> str | None:
        """Return a row's durable id or explain why its action cannot proceed."""
        todo_id = row.todo.todo_id
        if todo_id is None:
            logger.error(_ROW_ACTION_FAILURE_EVENT, action=_ROW_ACTION_RESOLVE_IDENTITY, slug=row.slug)
            return None
        return todo_id

    if TYPE_CHECKING:
        app: Any
        _projects_with_todos: list[ProjectWithTodosDTO]

        def _clear_dependency_flash(self) -> None: ...

        def _flash_dependencies(self) -> None: ...

    def _perform_identity_row_action(
        self,
        *,
        action: PreparationAction,
        method: str,
        path: str,
        todo_id: str,
        success_message: str,
        role_target: RoleTarget,
        body: object | None = None,
        params: ToolQueryParams | None = None,
        relay_warnings: bool = False,
        computer: str | None = None,
    ) -> None:
        """Run one row-addressed API action on the row's computer and contain transport failures at the UI edge."""
        try:
            result = tool_api_request(
                method,
                path,
                json_body=body,
                params=_with_computer(params, computer),
                timeout=10.0,
                clearance_scope=ClearanceScope.verb(
                    _ACTION_CLEARANCE_VERBS[action],
                    role_target=role_target,
                    target_computer=remote_computer(computer),
                ),
                clearance_identity=self.app._clearance_identity,  # type: ignore[attr-defined]
            )
        except ToolAPIError as exc:
            if exc.work_feedback is not None:
                self.app.present_work_feedback(exc.work_feedback)  # type: ignore[attr-defined]
            else:
                logger.error(
                    _ROW_ACTION_FAILURE_EVENT,
                    action=action.value,
                    todo_id=todo_id,
                    error=repr(exc),
                    exc_info=True,
                )
            return
        # Row actions cross the API boundary; contain unexpected failures before they unwind Textual.
        except Exception:
            logger.error(_ROW_ACTION_FAILURE_EVENT, action=action.value, todo_id=todo_id, exc_info=True)
            return

        if isinstance(result, dict) and result.get(_RESPONSE_KEY_STATUS) == _RESPONSE_STATUS_OK:
            self.app.notify_text(success_message)  # type: ignore[attr-defined]
            if relay_warnings:
                warnings = result.get(_WARNING_RESPONSE_KEY)
                if isinstance(warnings, list):
                    for warning in warnings:
                        if isinstance(warning, str):
                            self.app.notify_text(warning, severity=_NOTIFY_SEVERITY_WARNING)  # type: ignore[attr-defined]
            self.app._refresh_data()  # type: ignore[attr-defined]
            return
        if isinstance(result, dict) and result.get(_RESPONSE_KEY_DETAIL):
            logger.error(
                _ROW_ACTION_FAILURE_EVENT,
                action=action.value,
                todo_id=todo_id,
                detail=result[_RESPONSE_KEY_DETAIL],
            )
            return
        logger.error(_ROW_ACTION_FAILURE_EVENT, action=action.value, todo_id=todo_id, response=repr(result))

    @staticmethod
    def _next_command(base: str, slug: str | None) -> str:
        """Build lifecycle command with optional slug."""
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
            PreparationAction.FLASH_DEPENDENCIES,
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
            PreparationAction.FLASH_DEPENDENCIES,
        }
        file_disallowed = {
            "new_todo",
            "new_bug",
            "new_project",
            "freeze",
            "unfreeze",
            "approve_gate",
            "hold",
            PreparationAction.FLASH_DEPENDENCIES,
        }

        if isinstance(item, ComputerHeader):
            return action not in computer_only

        if isinstance(item, ProjectHeader):
            return action not in project_disallowed

        if isinstance(item, TodoRow):
            if item.todo.status in RETAINED_TODO_STATUSES and action in _ROW_ADDRESSED_ACTIONS:
                return action in _RETAINED_TODO_ACTIONS[item.todo.status].todo_row
            return self._check_todo_row_action(item, action)

        if isinstance(item, TodoFileRow):
            if item.status in RETAINED_TODO_STATUSES and action in _ROW_ADDRESSED_ACTIONS:
                return action in _RETAINED_TODO_ACTIONS[item.status].file_row
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
        self._clear_dependency_flash()
        if self.is_attached:  # type: ignore[attr-defined]
            self.app.refresh_bindings()  # type: ignore[attr-defined]
            self.call_after_refresh(self._sync_default_footer_action)  # type: ignore[attr-defined]

    def action_flash_dependencies(self) -> None:
        """Flash the selected todo's displayed dependencies."""
        PREPARATION_ACTION_HANDLERS[PreparationAction.FLASH_DEPENDENCIES](self)

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
            if self._is_expanded(row.todo.todo_id):  # type: ignore[attr-defined]
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
                        todo_id=file_row.todo_id,
                        computer=file_row.computer,
                    ),
                    command=self._editor_command(  # type: ignore[attr-defined]
                        project_path=file_row.project_path,
                        slug=file_row.slug,
                        artifact_name=file_row.artifact_name,
                        todo_id=file_row.todo_id,
                        computer=file_row.computer,
                        status=file_row.status,
                    ),
                    title=(
                        _VIEWING_FILE_TITLE_TEMPLATE.format(filename=file_row.filename)
                        if file_row.status in RETAINED_TODO_STATUSES
                        else _EDITING_FILE_TITLE_TEMPLATE.format(filename=file_row.filename)
                    ),
                )
            )

    def action_expand_all(self) -> None:
        """Expand every todo row in the current list."""
        for widget in list(self._nav_items):  # type: ignore[attr-defined]
            if isinstance(widget, TodoRow) and not self._is_expanded(widget.todo.todo_id):  # type: ignore[attr-defined]
                self._expand_todo(widget)  # type: ignore[attr-defined]

    def action_collapse_all(self) -> None:
        """Collapse every expanded todo row in the current list."""
        for widget in list(self._nav_items):  # type: ignore[attr-defined]
            if isinstance(widget, TodoRow) and self._is_expanded(widget.todo.todo_id):  # type: ignore[attr-defined]
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
        target_computer = context.computer if context else None
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
                        todo_id=file_row.todo_id,
                        computer=file_row.computer,
                    ),
                    command=self._editor_command(  # type: ignore[attr-defined]
                        project_path=file_row.project_path,
                        slug=file_row.slug,
                        artifact_name=file_row.artifact_name,
                        todo_id=file_row.todo_id,
                        computer=file_row.computer,
                        view=True,
                    ),
                    title=file_row.filename,
                )
            )

    def _current_project_path(self) -> str:
        """Return the active project path from cursor context or cwd."""
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        if context:
            return context.project_path
        return str(resolve_invocation_roots().invocation_dir)

    def _create_item(self, slug: str, *, kind: TodoDumpKind) -> None:
        """Create a todo or bug via the daemon API after content modal confirmation."""
        project_root = self._current_project_path()
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        computer = context.computer if context else None

        def _on_content(content: str | None) -> None:
            if not content or not content.strip():
                return

            request = TodoDumpRequest(
                slug=slug,
                content=content.strip(),
                kind=kind,
                cwd=project_root,
            )
            self.app.notify(_FILING_STARTED_TEMPLATE.format(slug=slug))  # type: ignore[attr-defined]
            self._submit_filing(request, project_root, computer, kind)

        self.app.push_screen(  # type: ignore[attr-defined]
            ContentInputModal(title=f"New {'Bug' if kind == 'bug' else 'Todo'}"),
            callback=_on_content,
        )

    def action_new_project(self) -> None:
        """n on computer header: open New Project modal."""
        item = self._current_item()  # type: ignore[attr-defined]
        if not isinstance(item, ComputerHeader):
            return

        computer = item.data.computer
        if not computer.is_local:
            self.app.notify_text(_REMOTE_PROJECT_NOTICE)  # type: ignore[attr-defined]
            return

        comp_name = computer.name
        existing_projects = [  # type: ignore[attr-defined]
            p for p in self._projects_with_todos if (p.computer or "local") == comp_name
        ]
        existing_paths = {p.path for p in existing_projects}

        def on_result(result: NewProjectResult | None) -> None:
            if not result:
                return
            start_new_project_save(self.app, result)  # type: ignore[attr-defined]

        self.app.push_screen(  # type: ignore[attr-defined]
            NewProjectModal(existing_paths=existing_paths),
            on_result,
        )

    def action_new_todo(self) -> None:
        """n: create a new todo via modal."""

        def _on_result(result: CreateSlugResult | None) -> None:
            if result:
                self._create_item(result.slug, kind=result.kind)

        self.app.push_screen(  # type: ignore[attr-defined]
            CreateSlugModal(title="New Todo"),
            callback=_on_result,
        )

    def action_new_bug(self) -> None:
        """b: create a new bug via modal."""

        def _on_result(result: CreateSlugResult | None) -> None:
            if result:
                self._create_item(result.slug, kind=result.kind)

        self.app.push_screen(  # type: ignore[attr-defined]
            CreateSlugModal(
                title=_NEW_BUG_MODAL_TITLE,
                placeholder=_NEW_BUG_SLUG_PLACEHOLDER,
                preset_kind=TODO_KIND_BUG,
            ),
            callback=_on_result,
        )

    def action_remove_artifact(self) -> None:
        """R: on an artifact row remove that artifact (≠ 'input'); on a todo row remove the todo."""
        file_row = self._current_file_row()  # type: ignore[attr-defined]
        if file_row is not None:
            artifact_name = file_row.artifact_name
            slug = file_row.slug
            if artifact_name == ARTIFACT_INPUT:
                self.app.notify(_INPUT_ARTIFACT_REMOVAL_WARNING, severity=_NOTIFY_SEVERITY_WARNING)  # type: ignore[attr-defined]
                return
            context = self._resolve_cursor_context()  # type: ignore[attr-defined]
            project_path = (context.project_path if context else "") or (file_row.project_path or "")
            computer = (context.computer if context else None) or file_row.computer
            if not project_path:
                self._report_unresolved_target(PreparationAction.REMOVE_ARTIFACT, slug)
                return

            def _on_confirm_artifact(confirmed: bool | None) -> None:
                if not confirmed:
                    return
                path = _TODO_BY_ID_ARTIFACT_PATH_TEMPLATE.format(
                    todo_id=quote(file_row.todo_id), name=quote(artifact_name)
                )
                self._perform_identity_row_action(
                    action=PreparationAction.REMOVE_ARTIFACT,
                    method=_ROW_ACTION_DELETE,
                    path=path,
                    todo_id=file_row.todo_id,
                    success_message=_REMOVE_ARTIFACT_SUCCESS_TEMPLATE.format(artifact_name=artifact_name, slug=slug),
                    role_target=ProjectPath(Path(project_path)),
                    params={_CWD_BODY_KEY: project_path},
                    computer=computer,
                )

            self.app.push_screen(  # type: ignore[attr-defined]
                ConfirmModal(
                    title=_REMOVE_ARTIFACT_MODAL_TITLE,
                    message=_REMOVE_ARTIFACT_CONFIRM_TEMPLATE.format(artifact_name=artifact_name, slug=slug),
                ),
                _on_confirm_artifact,
            )
            return

        # Todo row → remove the whole todo (original behavior).
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if row is None:
            return
        slug = row.slug
        todo_id = self._require_row_todo_id(row)
        if todo_id is None:
            return
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        project_path = context.project_path if context else ""
        computer = context.computer if context else None
        if not project_path:
            self._report_unresolved_target(PreparationAction.REMOVE_ARTIFACT, slug)
            return
        path = _TODO_BY_ID_ACTION_PATH_TEMPLATE.format(todo_id=quote(todo_id), action=_IdentityTodoRoute.REMOVE.value)

        def _on_confirm_todo(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._submit_lifecycle_operation(
                path,
                project_path,
                _REMOVING_TODO_LABEL_TEMPLATE.format(slug=slug),
                scope=ClearanceScope.verb(
                    "todo remove",
                    role_target=ProjectPath(Path(project_path)),
                    target_computer=remote_computer(computer),
                ),
            )

        self.app.push_screen(  # type: ignore[attr-defined]
            ConfirmModal(
                title=_REMOVE_TODO_MODAL_TITLE,
                message=_REMOVE_TODO_CONFIRM_TEMPLATE.format(slug=slug),
            ),
            _on_confirm_todo,
        )

    def _submit_lifecycle_operation(
        self,
        path: str,
        project_path: str,
        display_label: str,
        *,
        scope: ClearanceScope,
    ) -> None:
        computer = scope.target_computer
        try:
            result = tool_api_request(
                _ROW_ACTION_POST,
                path,
                json_body={_CWD_BODY_KEY: project_path},
                params=_with_computer(None, computer),
                timeout=10.0,
                clearance_scope=scope,
                clearance_identity=self.app._clearance_identity,  # type: ignore[attr-defined]
            )
        except ToolAPIError as exc:
            if exc.work_feedback is not None:
                self.app.present_work_feedback(exc.work_feedback)  # type: ignore[attr-defined]
            else:
                logger.error(_ROW_ACTION_FAILURE_EVENT, action=path, error=repr(exc), exc_info=True)
            return
        if isinstance(result, dict) and result.get("operation_id"):
            self.app.notify_text(f"{display_label}...")  # type: ignore[attr-defined]
            self.app._refresh_data()  # type: ignore[attr-defined]
            receipt_computer = result.get(_COMPUTER_PARAM)
            self._follow_lifecycle_operation(  # type: ignore[attr-defined]
                str(result["operation_id"]),
                scope,
                receipt_computer if isinstance(receipt_computer, str) else computer,
            )
            return
        if isinstance(result, dict) and result.get("detail"):
            logger.error(_ROW_ACTION_FAILURE_EVENT, action=path, detail=result["detail"])
            return
        logger.error(_ROW_ACTION_FAILURE_EVENT, action=path, response=repr(result))

    @work(thread=True, group=_FILING_WORKER_GROUP)
    def _submit_filing(
        self, request: TodoDumpRequest, project_root: str, computer: str | None, kind: TodoDumpKind
    ) -> None:
        """File a todo or bug off the event loop, so the TUI stays usable while the daemon works.

        ``tool_api_request`` is synchronous and a filing can wait on git and the workflow store; every
        notification crosses back via ``call_from_thread``.
        """
        app = self.app
        slug = request.slug
        try:
            result = tool_api_request(
                _ROW_ACTION_POST,
                _TODO_DUMP_PATH,
                json_body=request.model_dump(mode=_JSON_DUMP_MODE),
                params=_with_computer(None, computer),
                clearance_scope=ClearanceScope.verb(
                    _BUGS_REPORT_VERB if kind == TODO_KIND_BUG else _TODO_CREATE_VERB,
                    role_target=ProjectPath(Path(project_root)),
                    target_computer=remote_computer(computer),
                ),
                clearance_identity=app._clearance_identity,  # type: ignore[attr-defined]
            )
        except Exception as exc:
            feedback = getattr(exc, _WORK_FEEDBACK_ATTRIBUTE, None)
            if isinstance(feedback, str):
                app.call_from_thread(app.present_work_feedback, feedback)  # type: ignore[attr-defined]
            else:
                logger.error(_ROW_ACTION_FAILURE_EVENT, action=kind.value, slug=slug, exc_info=True)
                app.call_from_thread(
                    app.notify,
                    _FILING_FAILED_TEMPLATE.format(slug=slug, error=exc),
                    severity=_NOTIFY_SEVERITY_ERROR,
                )
            return
        if isinstance(result, dict) and result.get(_RESPONSE_KEY_STATUS) == _RESPONSE_STATUS_OK:
            app.call_from_thread(app.notify, _FILING_CREATED_TEMPLATE.format(slug=slug))
            return
        logger.error(_ROW_ACTION_FAILURE_EVENT, action=kind.value, slug=slug, response=repr(result))
        app.call_from_thread(
            app.notify,
            _FILING_FAILED_TEMPLATE.format(slug=slug, error=repr(result)),
            severity=_NOTIFY_SEVERITY_ERROR,
        )

    @work(thread=True, group="lifecycle-op")
    def _follow_lifecycle_operation(
        self, operation_id: str, scope: ClearanceScope, computer: str | None = None
    ) -> None:
        """Follow a submitted lifecycle operation to its terminal state.

        The receipt only confirms acceptance; the operation's real outcome
        (dispatched, refused, or failed) exists only after this point. Runs off
        the event loop because ``tool_api_request`` is synchronous; every
        notification crosses back via ``call_from_thread``.
        """
        start = time.monotonic()
        delay_s = 0.0
        response: object = None
        status_path = _OPERATION_STATUS_PATH_TEMPLATE.format(operation_id=operation_id)
        owner = remote_computer(computer)
        # An operation another computer owns is read there, as the operation read it is.
        poll_scope = ClearanceScope.verb(_OPERATION_READ_VERB, target_computer=owner) if owner is not None else scope
        while True:
            if delay_s > 0:
                time.sleep(delay_s)
            try:
                # Polling inherits the cleared lifecycle verb; it is not a separate `operations get` action.
                response = tool_api_request(
                    _HTTP_METHOD_GET,
                    status_path,
                    params=_with_computer(None, owner),
                    timeout=10.0,
                    clearance_scope=poll_scope,
                    clearance_identity=self.app._clearance_identity,  # type: ignore[attr-defined]
                )
            except ToolAPIError as exc:
                if time.monotonic() - start > _LIFECYCLE_POLL_BUDGET_S:
                    logger.error(
                        _OUTCOME_UNKNOWN_LOG,
                        operation_id=operation_id,
                        error=repr(exc),
                        exc_info=True,
                    )
                    return
                delay_s = _LIFECYCLE_POLL_DEFAULT_DELAY_S
                continue

            state = response.get(_OPERATION_RESPONSE_KEY_STATE) if isinstance(response, dict) else None
            if isinstance(state, str) and state in TERMINAL_OPERATION_STATES:
                self._report_lifecycle_outcome(response)  # type: ignore[attr-defined]
                return

            if time.monotonic() - start > _LIFECYCLE_POLL_BUDGET_S:
                recovery = (
                    response.get(_OPERATION_RESPONSE_KEY_RECOVERY_COMMAND) if isinstance(response, dict) else None
                )
                logger.error(
                    _OUTCOME_UNKNOWN_LOG,
                    operation_id=operation_id,
                    recovery_command=recovery or _RECOVERY_COMMAND_TEMPLATE.format(operation_id=operation_id),
                )
                return

            poll_after_ms = response.get(_OPERATION_RESPONSE_KEY_POLL_AFTER_MS) if isinstance(response, dict) else None
            delay_s = (
                poll_after_ms / 1000.0
                if isinstance(poll_after_ms, int) and poll_after_ms > 0
                else _LIFECYCLE_POLL_DEFAULT_DELAY_S
            )

    def _report_lifecycle_outcome(
        self,
        response: dict[str, object],  # guard: loose-dict - JSON-deserialized API response
    ) -> None:
        """Surface a terminal lifecycle-operation outcome to the operator."""
        state = response.get(_OPERATION_RESPONSE_KEY_STATE)
        work_feedback = response.get(_OPERATION_RESPONSE_KEY_WORK_FEEDBACK)
        operation_id = response.get(_OPERATION_RESPONSE_KEY_OPERATION_ID)
        if isinstance(work_feedback, str):
            self.app.call_from_thread(  # type: ignore[attr-defined]
                self.app.present_work_feedback,  # type: ignore[attr-defined]
                work_feedback,
                operation_id if isinstance(operation_id, str) else None,
            )
            return
        if state != _OPERATION_STATE_COMPLETED:
            logger.error(
                _OPERATION_OUTCOME_LOG,
                operation_id=operation_id,
                state=state,
                error=response.get(_OPERATION_RESPONSE_KEY_ERROR),
            )
        elif response.get(_OPERATION_RESPONSE_KEY_ERROR) is not None:
            logger.error(
                _OPERATION_OUTCOME_LOG,
                operation_id=operation_id,
                state=state,
                error=response.get(_OPERATION_RESPONSE_KEY_ERROR),
            )

    def action_prepare(self) -> None:
        """p: submit a prepare operation for the selected scope."""
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        computer = context.computer if context else None
        if not context:
            self._report_unresolved_target(PreparationAction.PREPARE, None)
            return
        project_path = context.project_path
        slug = context.slug
        if slug is None:
            self._submit_lifecycle_operation(
                _TODO_PREPARE_PATH,
                project_path,
                "Preparing",
                scope=ClearanceScope.verb(
                    "todo prepare",
                    role_target=ProjectPath(Path(project_path)),
                    target_computer=remote_computer(computer),
                ),
            )
            return
        row = self._resolve_todo_for_cursor()  # type: ignore[attr-defined]
        if row is None:
            self._report_unresolved_target(PreparationAction.PREPARE, slug)
            return
        todo_id = self._require_row_todo_id(row)
        if todo_id is None:
            return
        path = _TODO_BY_ID_ACTION_PATH_TEMPLATE.format(todo_id=quote(todo_id), action=_IdentityTodoRoute.PREPARE.value)
        self._submit_lifecycle_operation(
            path,
            project_path,
            _PREPARING_LABEL_TEMPLATE.format(slug=slug),
            scope=ClearanceScope.verb(
                "todo prepare", role_target=ProjectPath(Path(project_path)), target_computer=remote_computer(computer)
            ),
        )

    def action_start_work(self) -> None:
        """Submit a work operation and report the workflow's terminal outcome."""
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        computer = context.computer if context else None
        if not context:
            self._report_unresolved_target(PreparationAction.START_WORK, None)
            return
        project_path = context.project_path
        slug = context.slug
        todo_id = context.todo_id

        if slug is not None:
            todo_row = self._resolve_todo_for_cursor()  # type: ignore[attr-defined]
            if not todo_row:
                self._report_unresolved_target(PreparationAction.START_WORK, slug)
                return
            todo_id = self._require_row_todo_id(todo_row)
            if todo_id is None:
                return

        if slug is None:
            self._submit_lifecycle_operation(
                _TODO_WORK_PATH,
                project_path,
                "Starting work",
                scope=ClearanceScope.verb(
                    "todo work", role_target=ProjectPath(Path(project_path)), target_computer=remote_computer(computer)
                ),
            )
            return
        if todo_id is None:
            return
        path = _TODO_BY_ID_ACTION_PATH_TEMPLATE.format(todo_id=quote(todo_id), action=_IdentityTodoRoute.WORK.value)
        self._submit_lifecycle_operation(
            path,
            project_path,
            _STARTING_WORK_LABEL_TEMPLATE.format(slug=slug),
            scope=ClearanceScope.verb(
                "todo work", role_target=ProjectPath(Path(project_path)), target_computer=remote_computer(computer)
            ),
        )

    def action_freeze(self) -> None:
        """f: freeze a todo to the icebox."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if row is None:
            return
        slug = row.slug
        todo_id = self._require_row_todo_id(row)
        if todo_id is None:
            return

        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        computer = context.computer if context else None
        project_path = context.project_path if context else ""
        if not project_path:
            self._report_unresolved_target(PreparationAction.FREEZE, slug)
            return
        path = _TODO_BY_ID_ACTION_PATH_TEMPLATE.format(todo_id=quote(todo_id), action=_IdentityTodoRoute.FREEZE.value)

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._perform_identity_row_action(
                action=PreparationAction.FREEZE,
                method=_ROW_ACTION_POST,
                path=path,
                todo_id=todo_id,
                success_message=_FREEZE_SUCCESS_TEMPLATE.format(slug=slug),
                role_target=ProjectPath(Path(project_path)),
                computer=computer,
                body={_CWD_BODY_KEY: project_path},
                relay_warnings=True,
            )

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
            project_path = context.project_path
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
            project_path = context.project_path
            if project_path in self._delivered_projects:  # type: ignore[attr-defined]
                self._delivered_projects.discard(project_path)  # type: ignore[attr-defined]
            else:
                self._delivered_projects.add(project_path)  # type: ignore[attr-defined]

        self.post_message(StateChanged())  # type: ignore[attr-defined]
        self._rebuild()  # type: ignore[attr-defined]

    def action_unfreeze(self) -> None:
        """u: unfreeze an icebox todo back to the active todo list."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if row is None or row.todo.status != TodoStatus.ICEBOX:
            return

        slug = row.slug
        todo_id = self._require_row_todo_id(row)
        if todo_id is None:
            return
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        computer = context.computer if context else None
        project_path = context.project_path if context else ""
        if not project_path:
            self._report_unresolved_target(PreparationAction.UNFREEZE, slug)
            return

        path = _TODO_BY_ID_ACTION_PATH_TEMPLATE.format(todo_id=quote(todo_id), action=_IdentityTodoRoute.UNFREEZE.value)
        self._perform_identity_row_action(
            action=PreparationAction.UNFREEZE,
            method=_ROW_ACTION_POST,
            path=path,
            todo_id=todo_id,
            success_message=_UNFREEZE_SUCCESS_TEMPLATE.format(slug=slug),
            role_target=ProjectPath(Path(project_path)),
            computer=computer,
            body={_CWD_BODY_KEY: project_path},
            relay_warnings=True,
        )

    def action_hold(self) -> None:
        """h: hold an active todo with a reason, or release its existing hold."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if not row:
            return

        if not _hold_control_available(row):
            self.app.notify(_NO_HOLD_CONTROL_MESSAGE, severity=_NOTIFY_SEVERITY_WARNING)  # type: ignore[attr-defined]
            return

        slug = row.slug
        todo_id = self._require_row_todo_id(row)
        if todo_id is None:
            return
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        computer = context.computer if context else None
        project_path = context.project_path if context else ""
        if not project_path:
            self._report_unresolved_target(PreparationAction.HOLD, slug)
            return
        hold_path = _TODO_BY_ID_ACTION_PATH_TEMPLATE.format(
            todo_id=quote(todo_id), action=_IdentityTodoRoute.HOLD.value
        )

        if not row.todo.held:

            def _on_hold_reason(reason: str | None) -> None:
                if not reason:
                    return
                self._perform_identity_row_action(
                    action=PreparationAction.HOLD,
                    method=_ROW_ACTION_POST,
                    path=hold_path,
                    todo_id=todo_id,
                    success_message=_HOLD_SUCCESS_MESSAGE_TEMPLATE.format(slug=slug),
                    role_target=ProjectPath(Path(project_path)),
                    computer=computer,
                    body={_CWD_BODY_KEY: project_path, _REASON_BODY_KEY: reason.strip()},
                )

            self.app.push_screen(  # type: ignore[attr-defined]
                ContentInputModal(
                    title=_HOLD_MODAL_TITLE,
                    placeholder=_HOLD_MODAL_PLACEHOLDER,
                    prompt=_HOLD_MODAL_PROMPT,
                    submit_label=_HOLD_MODAL_SUBMIT_LABEL,
                ),
                callback=_on_hold_reason,
            )
            return

        release_path = _TODO_BY_ID_ACTION_PATH_TEMPLATE.format(
            todo_id=quote(todo_id), action=_IdentityTodoRoute.RELEASE.value
        )
        self._perform_identity_row_action(
            action=PreparationAction.HOLD,
            method=_ROW_ACTION_POST,
            path=release_path,
            todo_id=todo_id,
            success_message=_RELEASE_HOLD_SUCCESS_MESSAGE_TEMPLATE.format(slug=slug),
            role_target=ProjectPath(Path(project_path)),
            computer=computer,
            body={_CWD_BODY_KEY: project_path},
        )

    def action_approve_gate(self) -> None:
        """A: approve the selected todo's current human gate."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if row is None:
            return
        stamp_type = _pending_gate_stamp_type(row)
        if stamp_type is None:
            self.app.notify("No approval gate is pending for this todo", severity="warning")  # type: ignore[attr-defined]
            return

        slug = row.slug
        todo_id = self._require_row_todo_id(row)
        if todo_id is None:
            return
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        computer = context.computer if context else None
        project_path = context.project_path if context else ""
        if not project_path:
            self._report_unresolved_target(PreparationAction.APPROVE_GATE, slug)
            return

        path = _TODO_BY_ID_ACTION_PATH_TEMPLATE.format(todo_id=quote(todo_id), action=_IdentityTodoRoute.STAMP.value)
        self._perform_identity_row_action(
            action=PreparationAction.APPROVE_GATE,
            method=_ROW_ACTION_POST,
            path=path,
            todo_id=todo_id,
            success_message=_APPROVE_SUCCESS_TEMPLATE.format(slug=slug),
            role_target=ProjectPath(Path(project_path)),
            computer=computer,
            body={_CWD_BODY_KEY: project_path, _STAMP_TYPE_BODY_KEY: stamp_type},
        )

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
            project_path = context.project_path
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

        todo_id = self._require_row_todo_id(row)
        if todo_id is None:
            return

        slug = row.slug
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        computer = context.computer if context else None
        project_path = context.project_path if context else ""
        if not project_path:
            self._report_unresolved_target(PreparationAction.REACTIVATE_SELECTED, slug)
            return

        try:
            result = tool_api_request(
                "POST",
                f"/todos/by-id/{todo_id}/reactivate",
                json_body={"cwd": project_path},
                params=_with_computer(None, computer),
                timeout=10.0,
                clearance_scope=ClearanceScope.verb(
                    "todo reactivate",
                    role_target=ProjectPath(Path(project_path)),
                    target_computer=remote_computer(computer),
                ),
                clearance_identity=self.app._clearance_identity,  # type: ignore[attr-defined]
            )
            if isinstance(result, dict) and result.get("status") == "ok":
                self.app.notify_text(f"Restored '{slug}' to todo")  # type: ignore[attr-defined]
                # Rely on _on_mutation("todo_updated") to refresh via websocket,
                # but call refresh_data to be sure if needed.
                self.app._refresh_data()  # type: ignore[attr-defined]
            elif isinstance(result, dict) and result.get("detail"):
                logger.error(
                    _ROW_ACTION_FAILURE_EVENT,
                    action=PreparationAction.REACTIVATE_SELECTED.value,
                    todo_id=todo_id,
                    detail=result["detail"],
                )
        except Exception as exc:
            feedback = getattr(exc, "work_feedback", None)
            if isinstance(feedback, str):
                self.app.present_work_feedback(feedback)  # type: ignore[attr-defined]
            else:
                logger.error(
                    _ROW_ACTION_FAILURE_EVENT,
                    action=PreparationAction.REACTIVATE_SELECTED.value,
                    todo_id=todo_id,
                    exc_info=True,
                )


def _handle_flash_dependencies(view: PreparationViewActionsMixin) -> None:
    """Dispatch the dependency flash through its declared view capability."""
    view._flash_dependencies()


PREPARATION_ACTION_HANDLERS: dict[PreparationAction, Callable[[PreparationViewActionsMixin], None]] = {
    PreparationAction.FLASH_DEPENDENCIES: _handle_flash_dependencies,
}
