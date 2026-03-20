from __future__ import annotations

# guard: no-companion
import importlib
from unittest.mock import MagicMock

import pytest

todo_commands = importlib.import_module("teleclaude.cli.tool_commands.todo")

pytestmark = [
    pytest.mark.unit,
]


def test_handle_todo_state_reads_current_snapshot_when_only_slug_is_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_api_call = MagicMock(return_value={"current": "plan_review", "history": [], "valid_transitions": []})
    print_json = MagicMock()

    monkeypatch.setattr(todo_commands, "tool_api_call", tool_api_call)
    monkeypatch.setattr(todo_commands, "print_json", print_json)
    monkeypatch.setattr(todo_commands.os, "getcwd", lambda: "/tmp/project")

    todo_commands.handle_todo_state(["sample-slug"])

    tool_api_call.assert_called_once_with(
        "POST",
        "/todos/state",
        json_body={"slug": "sample-slug", "cwd": "/tmp/project"},
    )
    print_json.assert_called_once()


def test_handle_todo_state_fires_a_named_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_api_call = MagicMock(return_value={"current": "test_spec_build"})
    print_json = MagicMock()

    monkeypatch.setattr(todo_commands, "tool_api_call", tool_api_call)
    monkeypatch.setattr(todo_commands, "print_json", print_json)
    monkeypatch.setattr(todo_commands.os, "getcwd", lambda: "/tmp/project")

    todo_commands.handle_todo_state(["sample-slug", "approve_requirements"])

    tool_api_call.assert_called_once_with(
        "POST",
        "/todos/state",
        json_body={
            "slug": "sample-slug",
            "transition": "approve_requirements",
            "cwd": "/tmp/project",
        },
    )
    print_json.assert_called_once()


def test_handle_todo_state_requests_rewind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_api_call = MagicMock(return_value={"current": "requirements_review"})
    print_json = MagicMock()

    monkeypatch.setattr(todo_commands, "tool_api_call", tool_api_call)
    monkeypatch.setattr(todo_commands, "print_json", print_json)
    monkeypatch.setattr(todo_commands.os, "getcwd", lambda: "/tmp/project")

    todo_commands.handle_todo_state(["sample-slug", "--rewind"])

    tool_api_call.assert_called_once_with(
        "POST",
        "/todos/state",
        json_body={"slug": "sample-slug", "rewind": True, "cwd": "/tmp/project"},
    )
    print_json.assert_called_once()
