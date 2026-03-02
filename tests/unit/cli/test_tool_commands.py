"""Tests for tool CLI command handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pytest

from teleclaude.cli import tool_commands


@dataclass
class RunCallCapture:
    method: str = ""
    path: str = ""
    json_body: dict[str, str | bool] = field(default_factory=dict)


def test_handle_sessions_run_omits_agent_when_not_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    """sessions run should rely on API fallback unless --agent is explicitly provided."""
    captured = RunCallCapture()

    def fake_tool_api_call(
        method: str,
        path: str,
        json_body: object = None,
        *,
        params: dict[str, str] | None = None,
        timeout: float = 30.0,
        socket_path: str = "",
    ) -> object:
        _ = (params, timeout, socket_path)
        assert isinstance(json_body, dict)
        captured.method = method
        captured.path = path
        captured.json_body = cast(dict[str, str | bool], json_body)
        return {"status": "success"}

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_sessions_run(["--command", "/next-build", "--project", "/tmp/project"])

    assert captured.method == "POST"
    assert captured.path == "/sessions/run"
    body = captured.json_body
    assert "agent" not in body
    assert body["computer"] == "local"
    assert body["thinking_mode"] == "slow"
    assert body["args"] == ""


def test_handle_sessions_run_includes_explicit_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """sessions run should pass through explicit --agent."""
    captured = RunCallCapture()

    def fake_tool_api_call(
        method: str,
        path: str,
        json_body: object = None,
        *,
        params: dict[str, str] | None = None,
        timeout: float = 30.0,
        socket_path: str = "",
    ) -> object:
        _ = (method, path, params, timeout, socket_path)
        assert isinstance(json_body, dict)
        captured.json_body = cast(dict[str, str | bool], json_body)
        return {"status": "success"}

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_sessions_run(["--command", "/next-build", "--project", "/tmp/project", "--agent", "gemini"])

    assert captured.json_body["agent"] == "gemini"


def test_handle_sessions_start_passes_direct_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """sessions start should pass --direct through to API payload."""
    captured = RunCallCapture()

    def fake_tool_api_call(
        method: str,
        path: str,
        json_body: object = None,
        *,
        params: dict[str, str] | None = None,
        timeout: float = 30.0,
        socket_path: str = "",
    ) -> object:
        _ = (params, timeout, socket_path)
        assert isinstance(json_body, dict)
        captured.method = method
        captured.path = path
        captured.json_body = cast(dict[str, str | bool], json_body)
        return {"status": "success"}

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_sessions_start(["--project", "/tmp/project", "--direct"])

    assert captured.method == "POST"
    assert captured.path == "/sessions"
    assert captured.json_body["direct"] is True


def test_handle_sessions_send_positional_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    """sessions send should support positional message with --direct."""
    captured = RunCallCapture()

    def fake_tool_api_call(
        method: str,
        path: str,
        json_body: object = None,
        *,
        params: dict[str, str] | None = None,
        timeout: float = 30.0,
        socket_path: str = "",
    ) -> object:
        _ = (params, timeout, socket_path)
        assert isinstance(json_body, dict)
        captured.method = method
        captured.path = path
        captured.json_body = cast(dict[str, str | bool], json_body)
        return {"status": "success"}

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_sessions_send(["sess-123", "hello", "--direct"])

    assert captured.method == "POST"
    assert captured.path == "/sessions/sess-123/message"
    assert captured.json_body == {"message": "hello", "direct": True}


def test_handle_sessions_send_close_link_without_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """sessions send should allow --close-link without requiring a message."""
    captured = RunCallCapture()

    def fake_tool_api_call(
        method: str,
        path: str,
        json_body: object = None,
        *,
        params: dict[str, str] | None = None,
        timeout: float = 30.0,
        socket_path: str = "",
    ) -> object:
        _ = (params, timeout, socket_path)
        assert isinstance(json_body, dict)
        captured.method = method
        captured.path = path
        captured.json_body = cast(dict[str, str | bool], json_body)
        return {"status": "success"}

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_sessions_send(["sess-123", "--close-link"])

    assert captured.method == "POST"
    assert captured.path == "/sessions/sess-123/message"
    assert captured.json_body == {"close_link": True}


def test_handle_sessions_send_named_short_compatibility(monkeypatch: pytest.MonkeyPatch) -> None:
    """sessions send should accept short compatibility flags -s/-m."""
    captured = RunCallCapture()

    def fake_tool_api_call(
        method: str,
        path: str,
        json_body: object = None,
        *,
        params: dict[str, str] | None = None,
        timeout: float = 30.0,
        socket_path: str = "",
    ) -> object:
        _ = (params, timeout, socket_path)
        assert isinstance(json_body, dict)
        captured.method = method
        captured.path = path
        captured.json_body = cast(dict[str, str | bool], json_body)
        return {"status": "success"}

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_sessions_send(["-s", "sess-123", "-m", "hello"])

    assert captured.method == "POST"
    assert captured.path == "/sessions/sess-123/message"
    assert captured.json_body == {"message": "hello"}


# ---------------------------------------------------------------------------
# sessions end — 'self' resolution
# ---------------------------------------------------------------------------


@dataclass
class EndCallCapture:
    method: str = ""
    path: str = ""
    params: dict[str, str] = field(default_factory=dict)


def test_handle_sessions_end_resolves_self(monkeypatch: pytest.MonkeyPatch) -> None:
    """sessions end 'self' should resolve to the caller's session ID."""
    captured = EndCallCapture()

    def fake_tool_api_call(
        method: str,
        path: str,
        json_body: object = None,
        *,
        params: dict[str, str] | None = None,
        timeout: float = 30.0,
        socket_path: str = "",
    ) -> object:
        _ = (json_body, timeout, socket_path)
        captured.method = method
        captured.path = path
        captured.params = params or {}
        return {"status": "success"}

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)
    monkeypatch.setattr(tool_commands, "_read_caller_session_id", lambda: "real-session-42")

    tool_commands.handle_sessions_end(["self"])

    assert captured.method == "DELETE"
    assert captured.path == "/sessions/real-session-42"
    assert captured.params == {"computer": "local"}


def test_handle_sessions_end_self_fails_when_no_session_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """sessions end 'self' should exit 1 when session ID file is missing."""
    monkeypatch.setattr(tool_commands, "_read_caller_session_id", lambda: None)

    with pytest.raises(SystemExit, match="1"):
        tool_commands.handle_sessions_end(["self"])


def test_handle_sessions_end_literal_id_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """sessions end with a literal session ID should not attempt self-resolution."""
    captured = EndCallCapture()

    def fake_tool_api_call(
        method: str,
        path: str,
        json_body: object = None,
        *,
        params: dict[str, str] | None = None,
        timeout: float = 30.0,
        socket_path: str = "",
    ) -> object:
        _ = (json_body, timeout, socket_path)
        captured.method = method
        captured.path = path
        captured.params = params or {}
        return {"status": "success"}

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_sessions_end(["abc-123"])

    assert captured.method == "DELETE"
    assert captured.path == "/sessions/abc-123"
