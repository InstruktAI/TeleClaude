from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

todo_commands = importlib.import_module("teleclaude.cli.tool_commands.todo")
receipt_module = importlib.import_module("teleclaude.cli.tool_commands._receipt")


def test_handle_todo_prepare_invalidate_check_stays_local(monkeypatch: pytest.MonkeyPatch) -> None:
    print_json = MagicMock()

    monkeypatch.setattr(todo_commands, "print_json", print_json)
    monkeypatch.setattr(todo_commands.os, "getcwd", lambda: "/tmp/project")

    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setattr(
            todo_commands,
            "invalidate_stale_preparations",
            lambda cwd, changed_paths: {"cwd": cwd, "changed_paths": changed_paths},
        )
        todo_commands.handle_todo_prepare(["--invalidate-check", "--changed-paths", "a.py,b.py"])

    print_json.assert_called_once_with({"cwd": "/tmp/project", "changed_paths": ["a.py", "b.py"]})


def test_handle_todo_work_polls_until_terminal_state(monkeypatch: pytest.MonkeyPatch) -> None:
    print_json = MagicMock()
    responses = iter(
        [
            {"operation_id": "op-1", "state": "processing", "poll_after_ms": 10},
            {"operation_id": "op-1", "state": "completed"},
        ]
    )
    sleep_calls: list[float] = []

    monkeypatch.setattr(todo_commands, "print_json", print_json)
    monkeypatch.setattr(receipt_module, "print_json", print_json)
    monkeypatch.setattr(todo_commands.os, "getcwd", lambda: "/tmp/project")
    monkeypatch.setattr(todo_commands.uuid, "uuid4", lambda: "req-1")
    monkeypatch.setattr(receipt_module.time, "sleep", sleep_calls.append)

    def api_call(*_args: object, **_kwargs: object) -> object:
        return next(responses)

    monkeypatch.setattr(todo_commands, "tool_api_call", api_call)
    monkeypatch.setattr(receipt_module, "tool_api_call", api_call)

    todo_commands.handle_todo_work(["sample-slug"])

    assert sleep_calls == [0.01]
    print_json.assert_called_once_with({"operation_id": "op-1", "state": "completed"})


def test_handle_todo_integrate_polls_until_terminal_state(monkeypatch: pytest.MonkeyPatch) -> None:
    print_json = MagicMock()
    tool_api_call = MagicMock(
        side_effect=[
            {"operation_id": "op-1", "state": "running", "poll_after_ms": 10},
            {"operation_id": "op-1", "state": "completed"},
        ]
    )
    sleep_calls: list[float] = []

    monkeypatch.setattr(todo_commands, "print_json", print_json)
    monkeypatch.setattr(receipt_module, "print_json", print_json)
    monkeypatch.setattr(todo_commands.os, "getcwd", lambda: "/tmp/project")
    monkeypatch.setattr(receipt_module.time, "sleep", sleep_calls.append)
    monkeypatch.setattr(todo_commands, "tool_api_call", tool_api_call)
    monkeypatch.setattr(receipt_module, "tool_api_call", tool_api_call)

    todo_commands.handle_todo_integrate(["sample-slug"])

    assert sleep_calls == [0.01]
    assert tool_api_call.call_args_list[0].args == ("POST", "/todos/integrate")
    assert tool_api_call.call_args_list[1].args == ("GET", "/operations/op-1")
    print_json.assert_called_once_with({"operation_id": "op-1", "state": "completed"})


def test_handle_operations_routes_get(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[list[str]] = []

    monkeypatch.setattr(todo_commands, "handle_operations_get", received.append)

    todo_commands.handle_operations(["get", "op-1"])

    assert received == [["op-1"]]


def test_handle_todo_set_deps_posts_repeated_after_values(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_call = MagicMock(return_value={"ok": True})
    print_json = MagicMock()

    monkeypatch.setattr(todo_commands, "tool_api_call", tool_api_call)
    monkeypatch.setattr(todo_commands, "print_json", print_json)
    monkeypatch.setattr(todo_commands.os, "getcwd", lambda: "/tmp/project")

    todo_commands.handle_todo_set_deps(["sample-slug", "--after", "dep-a", "--after", "dep-b"])

    tool_api_call.assert_called_once_with(
        "POST",
        "/todos/set-deps",
        json_body={"slug": "sample-slug", "after": ["dep-a", "dep-b"], "cwd": "/tmp/project"},
    )
