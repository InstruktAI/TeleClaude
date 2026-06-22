"""Functional tests for TUI preparation actions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from teleclaude.api_models import ComputerDTO
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.tree import ComputerDisplayInfo
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.views import preparation_actions
from teleclaude.cli.tui.views.preparation_actions import PreparationViewActionsMixin
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.modals import ContentInputModal, CreateSlugModal
from teleclaude.cli.tui.widgets.todo_row import TodoRow

pytestmark = pytest.mark.functional

_DUMP_PATH = "/todos/dump"
_PREPARE_PATH = "/todos/prepare"
_WORK_PATH = "/todos/work"
_METHOD_POST = "POST"
_TODO_SLUG = "kindless-todo"
_BUG_SLUG = "broken-thing"
_CONTENT = "captured content\nwith multiple lines"
_KIND_BUG = "bug"


class _RecordingApp:
    def __init__(self) -> None:
        self.pushed: list[tuple[object, Callable[[str | None], None]]] = []
        self.notify = MagicMock()
        self._refresh_data = MagicMock()

    def push_screen(self, modal: object, callback: Callable[[str | None], None]) -> None:
        self.pushed.append((modal, callback))


class _Harness(PreparationViewActionsMixin):
    def __init__(self, project_root: Path) -> None:
        self.app = _RecordingApp()
        self._project_root = project_root
        self._slug_to_project_path = {"selected": str(project_root)}
        self._current: object | None = None

    def _current_item(self) -> object | None:
        return self._current

    def _current_todo_row(self) -> TodoRow | None:
        return self._current if isinstance(self._current, TodoRow) else None

    def _resolve_cursor_context(self) -> tuple[str, str, str | None] | None:
        return "local", str(self._project_root), "selected"

    def _resolve_todo_for_cursor(self) -> TodoRow | None:
        return self._current_todo_row()


def _drive_action(harness: _Harness, action: Callable[[], None], slug: str) -> None:
    action()
    slug_modal, slug_callback = harness.app.pushed.pop(0)
    assert isinstance(slug_modal, CreateSlugModal)

    slug_callback(slug)
    content_modal, content_callback = harness.app.pushed.pop(0)
    assert isinstance(content_modal, ContentInputModal)

    content_callback(_CONTENT)


def test_action_new_todo_dispatches_kindless(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)

    _drive_action(harness, harness.action_new_todo, _TODO_SLUG)

    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, _DUMP_PATH)
    json_body = tool_api_request.call_args.kwargs["json_body"]
    assert json_body["slug"] == _TODO_SLUG
    assert json_body["content"] == _CONTENT
    assert json_body["kind"] is None
    assert Path(json_body["cwd"]) == tmp_path


def test_action_new_bug_dispatches_bug_kind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)

    _drive_action(harness, harness.action_new_bug, _BUG_SLUG)

    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, _DUMP_PATH)
    json_body = tool_api_request.call_args.kwargs["json_body"]
    assert json_body["slug"] == _BUG_SLUG
    assert json_body["content"] == _CONTENT
    assert json_body["kind"] == _KIND_BUG
    assert Path(json_body["cwd"]) == tmp_path


def _todo_row(
    *,
    hold: bool = False,
    held: bool = False,
    status: TodoStatus = TodoStatus.IN_PROGRESS,
    lifecycle_phase: str = "plan_drafting",
    active_runner: str | None = None,
    kind: str = "change",
    task_plan_digest: str | None = None,
    task_approved_digest: str | None = None,
) -> TodoRow:
    item = TodoItem(
        slug="selected",
        status=status,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind=kind,
        lifecycle_phase=lifecycle_phase,
        hold=hold,
        held=held,
        active_runner=active_runner,
        task_plan_digest=task_plan_digest,
        task_approved_digest=task_approved_digest,
    )
    return TodoRow(item, slug_width=len(item.slug), col_widths=TodoRow.compute_col_widths([item]))


def test_hold_action_releases_when_effectively_held(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)

    # The offered control IS the unhold control: present exactly when the todo is
    # effectively held, and it clears the flag (release).
    harness._current = _todo_row(hold=True, held=True, lifecycle_phase="build_started")
    assert harness.check_action("hold", ()) is True
    harness.action_hold()

    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, "/todos/update")
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
        "release": True,
    }

    # A todo that is not effectively held offers no control.
    harness._current = _todo_row(hold=False, held=False, lifecycle_phase="build_started")
    assert harness.check_action("hold", ()) is False

    harness._current = _todo_row(hold=True, held=True, status=TodoStatus.ICEBOX)
    assert harness.check_action("hold", ()) is False


def test_hold_control_suppressed_when_not_effectively_held(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)

    # A residual hold whose derived verdict is not effectively held (autostart
    # off, runner manual, or still in the prepare lane) offers no control.
    harness._current = _todo_row(hold=True, held=False, lifecycle_phase="prepared")
    assert harness.check_action("hold", ()) is False


def test_release_action_does_not_exist(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)
    assert not hasattr(harness, "action_release")
    assert not hasattr(harness, "action_release_hold")


def test_approve_and_hold_are_independent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)

    # The approval gate is observed independently of the hold flag.
    harness._current = _todo_row(hold=True, held=False, lifecycle_phase="prd_human_approval")
    assert harness.check_action("approve_gate", ()) is True

    # The unhold control is exposed for an effectively-held todo regardless of
    # any approval state, and an approval gate does not suppress it.
    harness._current = _todo_row(hold=True, held=True, lifecycle_phase="build_started")
    assert harness.check_action("hold", ()) is True

    harness._current = _todo_row(hold=True, held=False, lifecycle_phase="prd_human_approval")
    harness.action_approve_gate()
    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, "/todos/stamp")
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
        "stamp_type": "prd_approved",
        "notify_runner": True,
    }


def test_no_human_gate_controls_for_running_or_work_ready_todos(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)

    # Prepared with a residual hold that is not effectively held: no approval
    # pending, no unhold control.
    harness._current = _todo_row(lifecycle_phase="prepared", hold=True, held=False)
    assert harness.check_action("approve_gate", ()) is False
    assert harness.check_action("hold", ()) is False

    harness._current = _todo_row(active_runner="runner-session", lifecycle_phase="plan_drafting")
    assert harness.check_action("approve_gate", ()) is False
    assert harness.check_action("hold", ()) is False


def test_task_authorization_uses_task_approved_stamp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)
    harness._current = _todo_row(
        kind="task",
        lifecycle_phase="prepared",
        task_plan_digest="plan-digest",
        task_approved_digest=None,
    )

    assert harness.check_action("approve_gate", ()) is True
    harness.action_approve_gate()

    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, "/todos/stamp")
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
        "stamp_type": "task_approved",
        "notify_runner": True,
    }


def test_task_authorization_action_suppressed_when_digest_current(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)
    harness._current = _todo_row(
        kind="task",
        lifecycle_phase="prepared",
        task_plan_digest="plan-digest",
        task_approved_digest="plan-digest",
    )

    assert harness.check_action("approve_gate", ()) is False


def test_computer_header_action_gating(tmp_path: Path) -> None:
    computer = ComputerDTO(name="test-comp", status="active", is_local=True)
    header = ComputerHeader(ComputerDisplayInfo(computer=computer, session_count=0, recent_activity=False))
    harness = _Harness(tmp_path)
    harness._current = header

    assert harness.check_action("toggle_delivered", ()) is False
    assert harness.check_action("toggle_icebox", ()) is False
    assert harness.check_action("toggle_trashed", ()) is False
    assert harness.check_action("new_project", ()) is True


def test_action_prepare_posts_operation_instead_of_opening_session_modal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool_api_request = MagicMock(return_value={"operation_id": "op-prepare"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)
    harness._current = _todo_row()

    harness.action_prepare()

    assert harness.app.pushed == []
    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, _PREPARE_PATH)
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
    }
    harness.app._refresh_data.assert_called_once()


def test_action_start_work_posts_operation_after_readiness_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool_api_request = MagicMock(return_value={"operation_id": "op-work"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)
    harness._current = _todo_row(lifecycle_phase="prepared")

    harness.action_start_work()

    assert harness.app.pushed == []
    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, _WORK_PATH)
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
    }
    harness.app._refresh_data.assert_called_once()
