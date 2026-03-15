from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

todo_commands = importlib.import_module("teleclaude.cli.tool_commands.todo")


def test_handle_todo_prepare_invalidate_check_stays_local(monkeypatch: pytest.MonkeyPatch) -> None:
    print_json = MagicMock()

    monkeypatch.setattr(todo_commands, "print_json", print_json)
    monkeypatch.setattr(todo_commands.os, "getcwd", lambda: "/tmp/project")

    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules,
            "teleclaude.core.next_machine.core",
            SimpleNamespace(
                invalidate_stale_preparations=lambda cwd, changed_paths: {"cwd": cwd, "changed_paths": changed_paths}
            ),
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
    monkeypatch.setattr(todo_commands.os, "getcwd", lambda: "/tmp/project")
    monkeypatch.setattr(todo_commands.uuid, "uuid4", lambda: "req-1")
    monkeypatch.setattr(todo_commands.time, "sleep", lambda delay: sleep_calls.append(delay))
    monkeypatch.setattr(todo_commands, "tool_api_call", lambda *_args, **_kwargs: next(responses))

    todo_commands.handle_todo_work(["sample-slug"])

    assert sleep_calls == [0.01]
    print_json.assert_called_once_with({"operation_id": "op-1", "state": "completed"})


def test_handle_operations_routes_get(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[list[str]] = []

    monkeypatch.setattr(todo_commands, "handle_operations_get", lambda args: received.append(args))

    todo_commands.handle_operations(["get", "op-1"])

    assert received == [["op-1"]]


def test_handle_todo_mark_phase_requires_slug(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        todo_commands.handle_todo_mark_phase(["--phase", "build", "--status", "complete"])

    assert exc_info.value.code == 1
    assert "slug is required" in capsys.readouterr().err


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
