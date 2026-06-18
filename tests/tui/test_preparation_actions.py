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
    status: TodoStatus = TodoStatus.IN_PROGRESS,
    lifecycle_phase: str = "plan_drafting",
    active_runner: str | None = None,
) -> TodoRow:
    item = TodoItem(
        slug="selected",
        status=status,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind="change",
        lifecycle_phase=lifecycle_phase,
        hold=hold,
        active_runner=active_runner,
    )
    return TodoRow(item, slug_width=len(item.slug), col_widths=TodoRow.compute_col_widths([item]))


def _enable_autostart(monkeypatch: pytest.MonkeyPatch, kind: str, *, enabled: bool = True) -> None:
    monkeypatch.setattr(preparation_actions.config.workflow.autostart, kind, enabled)


def test_hold_action_posts_hold_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    _enable_autostart(monkeypatch, "change")
    harness = _Harness(tmp_path)

    # Hold control is the prepared -> work brake: only on a prepared, unheld,
    # autostart-enabled todo.
    harness._current = _todo_row(hold=False, lifecycle_phase="prepared")
    assert harness.check_action("hold", ()) is True
    harness.action_hold()

    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, "/todos/update")
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
        "hold": True,
    }

    # No release control: an already-held todo offers no hold affordance.
    harness._current = _todo_row(hold=True, lifecycle_phase="prepared")
    assert harness.check_action("hold", ()) is False

    # Not prepared -> no hold control even when autostart-enabled.
    harness._current = _todo_row(hold=False, lifecycle_phase="plan_drafting")
    assert harness.check_action("hold", ()) is False

    harness._current = _todo_row(status=TodoStatus.ICEBOX)
    assert harness.check_action("hold", ()) is False


def test_hold_control_requires_autostart_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _enable_autostart(monkeypatch, "change", enabled=False)
    harness = _Harness(tmp_path)

    harness._current = _todo_row(hold=False, lifecycle_phase="prepared")
    assert harness.check_action("hold", ()) is False


def test_release_action_does_not_exist(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)
    assert not hasattr(harness, "action_release")
    assert not hasattr(harness, "action_release_hold")


def test_approve_and_hold_are_independent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    _enable_autostart(monkeypatch, "change")
    harness = _Harness(tmp_path)

    # A prepared row that is BOTH held and (hypothetically) approval-pending would
    # show both predicates; approval and hold no longer exclude one another. The
    # approval gate is observed independently of the hold flag.
    harness._current = _todo_row(hold=True, lifecycle_phase="prd_human_approval")
    assert harness.check_action("approve_gate", ()) is True

    # Held does not suppress an approval gate, and a pending approval gate does
    # not suppress the hold predicate: a prepared, unheld, autostart-enabled row
    # exposes the hold control regardless of approval state.
    harness._current = _todo_row(hold=False, lifecycle_phase="prepared")
    assert harness.check_action("hold", ()) is True

    harness.action_approve_gate()  # no-op here (not approval-pending) but exercises path
    harness._current = _todo_row(hold=True, lifecycle_phase="prd_human_approval")
    harness.action_approve_gate()
    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, "/todos/stamp")
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
        "stamp_type": "prd_approved",
        "notify_runner": True,
    }


def test_no_human_gate_controls_for_running_or_work_ready_todos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _enable_autostart(monkeypatch, "change")
    harness = _Harness(tmp_path)

    # Prepared + held: approval not pending, hold control suppressed (already held).
    harness._current = _todo_row(lifecycle_phase="prepared", hold=True)
    assert harness.check_action("approve_gate", ()) is False
    assert harness.check_action("hold", ()) is False

    harness._current = _todo_row(active_runner="runner-session", lifecycle_phase="plan_drafting")
    assert harness.check_action("approve_gate", ()) is False
    assert harness.check_action("hold", ()) is False


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
