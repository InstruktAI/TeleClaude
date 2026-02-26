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
    json_body: dict[str, str] = field(default_factory=dict)


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
        captured.json_body = cast(dict[str, str], json_body)
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
        captured.json_body = cast(dict[str, str], json_body)
        return {"status": "success"}

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_sessions_run(["--command", "/next-build", "--project", "/tmp/project", "--agent", "gemini"])

    assert captured.json_body["agent"] == "gemini"
