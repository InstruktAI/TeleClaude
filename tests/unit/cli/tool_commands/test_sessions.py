from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sessions = importlib.import_module("teleclaude.cli.tool_commands.sessions")


def test_handle_sessions_routes_revive_to_telec_misc() -> None:
    received: list[list[str]] = []

    with pytest.MonkeyPatch.context() as sys_patch:
        sys_patch.setattr(sessions, "_handle_revive", received.append)
        sessions.handle_sessions(["revive", "sess-1", "--attach"])

    assert received == [["sess-1", "--attach"]]


def test_handle_sessions_start_defaults_project_to_invocation_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    # The project default must come from the caller's invocation cwd, not Path.cwd()
    # — under the `telec` wrapper (`uv run --directory <install>`) Path.cwd() is the
    # install dir, which would dispatch sessions into the wrong project.
    tool_api_call = MagicMock(return_value={"session_id": "sess-1"})
    monkeypatch.setattr(sessions, "tool_api_call", tool_api_call)
    monkeypatch.setattr(sessions, "print_json", MagicMock())
    monkeypatch.setattr(sessions, "resolve_invocation_cwd", lambda: Path("/caller/project"))

    sessions.handle_sessions_start(["--agent", "claude"])

    call_body = tool_api_call.call_args[1]["json_body"]
    assert call_body["project_path"] == str(Path("/caller/project"))


def test_handle_sessions_run_defaults_project_to_invocation_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: a `/next-*` dispatch with no --project must target the caller's
    # project (invocation cwd), not the daemon/install dir.
    tool_api_call = MagicMock(return_value={"session_id": "sess-1"})
    monkeypatch.setattr(sessions, "tool_api_call", tool_api_call)
    monkeypatch.setattr(sessions, "print_json", MagicMock())
    monkeypatch.setattr(sessions, "resolve_invocation_cwd", lambda: Path("/caller/project"))

    sessions.handle_sessions_run(["--command", "/next-review-commits", "--args", "abc123"])

    call_body = tool_api_call.call_args[1]["json_body"]
    assert call_body["project"] == str(Path("/caller/project"))


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


def test_handle_sessions_tail_defaults_to_latest_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_call = MagicMock(return_value={"messages": []})
    print_json = MagicMock()

    monkeypatch.setattr(sessions, "tool_api_call", tool_api_call)
    monkeypatch.setattr(sessions, "print_json", print_json)

    sessions.handle_sessions_tail(["sess-1"])

    tool_api_call.assert_called_once_with(
        "GET",
        "/sessions/sess-1/messages",
        params={"tail_scope": "latest_turn"},
    )
    print_json.assert_called_once_with({"messages": []})


def test_handle_sessions_tail_since_widens_to_all_since_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_call = MagicMock(return_value={"messages": []})

    monkeypatch.setattr(sessions, "tool_api_call", tool_api_call)
    monkeypatch.setattr(sessions, "print_json", MagicMock())

    sessions.handle_sessions_tail(["sess-1", "--since", "2026-05-22T00:00:00Z"])

    tool_api_call.assert_called_once_with(
        "GET",
        "/sessions/sess-1/messages",
        params={"since": "2026-05-22T00:00:00Z", "tail_scope": "all"},
    )


def test_handle_sessions_tail_full_widens_to_all_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_call = MagicMock(return_value={"messages": []})

    monkeypatch.setattr(sessions, "tool_api_call", tool_api_call)
    monkeypatch.setattr(sessions, "print_json", MagicMock())

    sessions.handle_sessions_tail(["sess-1", "--full"])

    tool_api_call.assert_called_once_with(
        "GET",
        "/sessions/sess-1/messages",
        params={"tail_scope": "all"},
    )


def test_handle_sessions_end_resolves_self(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_call = MagicMock(return_value={"ok": True})
    print_json = MagicMock()

    monkeypatch.setattr(sessions, "get_session_id", lambda: "caller-1")
    monkeypatch.setattr(sessions, "tool_api_call", tool_api_call)
    monkeypatch.setattr(sessions, "print_json", print_json)

    sessions.handle_sessions_end(["self"])

    tool_api_call.assert_called_once_with("DELETE", "/sessions/caller-1", params={"computer": "local"})


def test_handle_sessions_widget_rejects_invalid_json(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        sessions.handle_sessions_widget(["--data", "{bad"])

    assert exc_info.value.code == 1
    assert "invalid JSON" in capsys.readouterr().err
