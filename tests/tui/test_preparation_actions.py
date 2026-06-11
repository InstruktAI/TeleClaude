"""Functional tests for TUI preparation actions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from teleclaude.cli.tui.views import preparation_actions
from teleclaude.cli.tui.views.preparation_actions import PreparationViewActionsMixin
from teleclaude.cli.tui.widgets.modals import ContentInputModal, CreateSlugModal

pytestmark = pytest.mark.functional

_DUMP_PATH = "/todos/dump"
_METHOD_POST = "POST"
_TODO_SLUG = "kindless-todo"
_BUG_SLUG = "broken-thing"
_CONTENT = "captured content"
_KIND_BUG = "bug"


class _RecordingApp:
    def __init__(self) -> None:
        self.pushed: list[tuple[object, Callable[[str | None], None]]] = []
        self.notify = MagicMock()

    def push_screen(self, modal: object, callback: Callable[[str | None], None]) -> None:
        self.pushed.append((modal, callback))


class _Harness(PreparationViewActionsMixin):
    def __init__(self, project_root: Path) -> None:
        self.app = _RecordingApp()
        self._slug_to_project_path = {"selected": str(project_root)}


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
