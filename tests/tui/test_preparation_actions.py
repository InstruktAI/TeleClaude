"""Functional tests for TUI preparation actions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.views import preparation_actions
from teleclaude.cli.tui.views.preparation_actions import PreparationViewActionsMixin
from teleclaude.cli.tui.widgets.modals import ContentInputModal, CreateSlugModal
from teleclaude.cli.tui.widgets.todo_row import TodoRow

pytestmark = pytest.mark.functional

_DUMP_PATH = "/todos/dump"
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
        self._slug_to_project_path = {"selected": str(project_root)}
        self._current: object | None = None

    def _current_item(self) -> object | None:
        return self._current

    def _current_todo_row(self) -> TodoRow | None:
        return self._current if isinstance(self._current, TodoRow) else None


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


def test_toggle_hold_action_posts_hold_or_release(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)

    harness._current = _todo_row(hold=False)
    assert harness.check_action("toggle_hold", ()) is True
    harness.action_toggle_hold()

    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, "/todos/update")
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
        "hold": True,
    }

    harness._current = _todo_row(hold=True)
    harness.action_toggle_hold()

    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
        "release": True,
    }
    assert harness.check_action("toggle_hold", ()) is True
    harness._current = _todo_row(status=TodoStatus.ICEBOX)
    assert harness.check_action("toggle_hold", ()) is False


def test_approve_gate_action_posts_approve_and_excludes_hold(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(preparation_actions, "tool_api_request", tool_api_request)
    harness = _Harness(tmp_path)

    harness._current = _todo_row(hold=True, lifecycle_phase="prd_human_approval")

    assert harness.check_action("approve_gate", ()) is True
    assert harness.check_action("toggle_hold", ()) is False
    harness.action_approve_gate()

    assert tool_api_request.call_args.args[:2] == (_METHOD_POST, "/todos/approve")
    assert tool_api_request.call_args.kwargs["json_body"] == {
        "slug": "selected",
        "cwd": str(tmp_path),
    }
    harness.app._refresh_data.assert_called_once()


def test_no_human_gate_controls_for_running_or_work_ready_todos(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)

    harness._current = _todo_row(lifecycle_phase="prepared")
    assert harness.check_action("approve_gate", ()) is False
    assert harness.check_action("toggle_hold", ()) is False

    harness._current = _todo_row(active_runner="runner-session")
    assert harness.check_action("approve_gate", ()) is False
    assert harness.check_action("toggle_hold", ()) is False
