from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sessions = importlib.import_module("teleclaude.cli.tool_commands.sessions")


def test_handle_sessions_routes_revive_to_telec_misc() -> None:
    received: list[list[str]] = []

    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setitem(
            sys.modules,
            "teleclaude.cli.telec.handlers.misc",
            SimpleNamespace(_handle_revive=lambda args: received.append(args)),
        )
        sessions.handle_sessions(["revive", "sess-1", "--attach"])

    assert received == [["sess-1", "--attach"]]


def test_handle_sessions_start_requires_project(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        sessions.handle_sessions_start(["--agent", "claude"])

    assert exc_info.value.code == 1
    assert "--project is required" in capsys.readouterr().err


def test_handle_sessions_start_posts_launch_body(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_call = MagicMock(return_value={"session_id": "sess-1"})
    print_json = MagicMock()

    monkeypatch.setattr(sessions, "tool_api_call", tool_api_call)
    monkeypatch.setattr(sessions, "print_json", print_json)

    sessions.handle_sessions_start(
        ["--project", "/tmp/project", "--agent", "codex", "--message", "hi", "--direct", "--detach"]
    )

    tool_api_call.assert_called_once_with(
        "POST",
        "/sessions",
        json_body={
            "computer": "local",
            "launch_kind": "agent_then_message",
            "project_path": "/tmp/project",
            "agent": "codex",
            "message": "hi",
            "direct": True,
            "skip_listener_registration": True,
        },
    )


def test_handle_sessions_send_uses_positional_message_and_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_call = MagicMock(return_value={"ok": True})
    print_json = MagicMock()

    monkeypatch.setattr(sessions, "tool_api_call", tool_api_call)
    monkeypatch.setattr(sessions, "print_json", print_json)

    sessions.handle_sessions_send(["sess-1", "hello", "world", "--direct"])

    tool_api_call.assert_called_once_with(
        "POST",
        "/sessions/sess-1/message",
        json_body={"message": "hello world", "direct": True},
    )


def test_handle_sessions_end_resolves_self(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_call = MagicMock(return_value={"ok": True})
    print_json = MagicMock()

    monkeypatch.setattr(sessions, "_read_caller_session_id", lambda: "caller-1")
    monkeypatch.setattr(sessions, "tool_api_call", tool_api_call)
    monkeypatch.setattr(sessions, "print_json", print_json)

    sessions.handle_sessions_end(["self"])

    tool_api_call.assert_called_once_with("DELETE", "/sessions/caller-1", params={"computer": "local"})


def test_handle_sessions_widget_rejects_invalid_json(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        sessions.handle_sessions_widget(["--data", "{bad"])

    assert exc_info.value.code == 1
    assert "invalid JSON" in capsys.readouterr().err
