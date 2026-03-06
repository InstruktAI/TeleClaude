from __future__ import annotations

import pytest

from teleclaude.cli import tool_commands


def test_todo_work_uses_shell_cwd_when_slug_omitted(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    captured = {}

    def fake_tool_api_call(
        method: str,
        path: str,
        *,
        json_body=None,
        params=None,
        timeout: float = 30.0,
        socket_path: str = "",
    ):
        _ = (timeout, socket_path)
        captured["method"] = method
        captured["path"] = path
        captured["json_body"] = json_body
        return {
            "operation_id": "op-123",
            "state": "completed",
            "poll_after_ms": 1,
            "recovery_command": "telec operations get op-123",
            "result": "NEXT_WORK COMPLETE",
        }

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_todo_work([])

    assert captured["method"] == "POST"
    assert captured["path"] == "/todos/work"
    json_body = captured["json_body"]
    assert isinstance(json_body, dict)
    assert json_body.get("cwd") == str(tmp_path)
    assert isinstance(json_body.get("client_request_id"), str)
    assert "slug" not in json_body


def test_todo_work_uses_shell_cwd_with_slug(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    captured = {}

    def fake_tool_api_call(
        method: str,
        path: str,
        *,
        json_body=None,
        params=None,
        timeout: float = 30.0,
        socket_path: str = "",
    ):
        _ = (method, path, params, timeout, socket_path)
        captured["json_body"] = json_body
        return {
            "operation_id": "op-123",
            "state": "completed",
            "poll_after_ms": 1,
            "recovery_command": "telec operations get op-123",
            "result": "NEXT_WORK COMPLETE",
        }

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_todo_work(["mature-deployment"])

    json_body = captured["json_body"]
    assert isinstance(json_body, dict)
    assert json_body.get("slug") == "mature-deployment"
    assert json_body.get("cwd") == str(tmp_path)
    assert isinstance(json_body.get("client_request_id"), str)


def test_todo_work_ignores_legacy_cwd_flag(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    captured = {}

    def fake_tool_api_call(
        method: str,
        path: str,
        *,
        json_body=None,
        params=None,
        timeout: float = 30.0,
        socket_path: str = "",
    ):
        _ = (method, path, params, timeout, socket_path)
        captured["json_body"] = json_body
        return {
            "operation_id": "op-123",
            "state": "completed",
            "poll_after_ms": 1,
            "recovery_command": "telec operations get op-123",
            "result": "NEXT_WORK COMPLETE",
        }

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_todo_work(["mature-deployment", "--cwd", "/tmp/not-used"])

    json_body = captured["json_body"]
    assert isinstance(json_body, dict)
    assert json_body.get("slug") == "mature-deployment"
    assert json_body.get("cwd") == str(tmp_path)
    assert isinstance(json_body.get("client_request_id"), str)


def test_todo_work_submits_then_polls_until_terminal(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls: list[tuple[str, str, object | None]] = []
    printed: list[object] = []
    responses = iter(
        [
            {
                "operation_id": "op-123",
                "state": "queued",
                "poll_after_ms": 1,
                "recovery_command": "telec operations get op-123",
            },
            {
                "operation_id": "op-123",
                "state": "running",
                "poll_after_ms": 1,
                "recovery_command": "telec operations get op-123",
                "progress_phase": "dispatch_decision",
            },
            {
                "operation_id": "op-123",
                "state": "completed",
                "poll_after_ms": 1,
                "recovery_command": "telec operations get op-123",
                "result": "NEXT_WORK COMPLETE",
            },
        ]
    )

    def fake_tool_api_call(
        method: str,
        path: str,
        *,
        json_body=None,
        params=None,
        timeout: float = 30.0,
        socket_path: str = "",
    ):
        _ = (params, timeout, socket_path)
        calls.append((method, path, json_body))
        return next(responses)

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda data: printed.append(data))
    monkeypatch.setattr(tool_commands.time, "sleep", lambda _seconds: None)

    tool_commands.handle_todo_work(["mature-deployment"])

    assert len(calls) == 3
    assert calls[0][0] == "POST"
    assert calls[0][1] == "/todos/work"
    assert isinstance(calls[0][2], dict)
    assert calls[0][2]["cwd"] == str(tmp_path)
    assert calls[0][2]["slug"] == "mature-deployment"
    assert isinstance(calls[0][2]["client_request_id"], str)
    assert calls[1:] == [
        ("GET", "/operations/op-123", None),
        ("GET", "/operations/op-123", None),
    ]
    assert printed == [
        {
            "operation_id": "op-123",
            "state": "completed",
            "poll_after_ms": 1,
            "recovery_command": "telec operations get op-123",
            "result": "NEXT_WORK COMPLETE",
        }
    ]


def test_todo_work_prints_recovery_handle_when_poll_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    calls: list[tuple[str, str]] = []

    def fake_tool_api_call(
        method: str,
        path: str,
        *,
        json_body=None,
        params=None,
        timeout: float = 30.0,
        socket_path: str = "",
    ):
        _ = (json_body, params, timeout, socket_path)
        calls.append((method, path))
        if len(calls) == 1:
            return {
                "operation_id": "op-123",
                "state": "queued",
                "poll_after_ms": 1,
                "recovery_command": "telec operations get op-123",
            }
        raise SystemExit(1)

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands.time, "sleep", lambda _seconds: None)

    with pytest.raises(SystemExit):
        tool_commands.handle_todo_work(["mature-deployment"])

    err = capsys.readouterr().err
    assert "telec operations get op-123" in err


def test_operations_get_fetches_status(monkeypatch):
    captured = {}
    printed: list[object] = []

    def fake_tool_api_call(
        method: str,
        path: str,
        *,
        json_body=None,
        params=None,
        timeout: float = 30.0,
        socket_path: str = "",
    ):
        _ = (json_body, params, timeout, socket_path)
        captured["method"] = method
        captured["path"] = path
        return {
            "operation_id": "op-123",
            "state": "running",
            "poll_after_ms": 250,
            "recovery_command": "telec operations get op-123",
        }

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda data: printed.append(data))

    tool_commands.handle_operations(["get", "op-123"])

    assert captured == {"method": "GET", "path": "/operations/op-123"}
    assert printed == [
        {
            "operation_id": "op-123",
            "state": "running",
            "poll_after_ms": 250,
            "recovery_command": "telec operations get op-123",
        }
    ]
