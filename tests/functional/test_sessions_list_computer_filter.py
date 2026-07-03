"""Functional bindings for list command computer filters."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.cli.telec.help import _maybe_show_help
from teleclaude.cli.telec.surface import CLI_SURFACE
from teleclaude.cli.tool_commands import sessions as sessions_tool

pytestmark = pytest.mark.functional


def test_sessions_list_forwards_computer(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_call = MagicMock(return_value={"sessions": []})
    monkeypatch.setattr(sessions_tool, "tool_api_call", tool_api_call)
    monkeypatch.setattr(sessions_tool, "print_json", lambda data: None)

    sessions_tool.handle_sessions_list(["--computer", "MozMini"])

    assert tool_api_call.call_args.args[:2] == ("GET", "/sessions")
    assert tool_api_call.call_args.kwargs["params"] == {"computer": "MozMini"}

    tool_api_call.reset_mock()
    sessions_tool.handle_sessions_list([])

    assert tool_api_call.call_args.args[:2] == ("GET", "/sessions")
    assert "computer" not in tool_api_call.call_args.kwargs["params"]


def test_sessions_list_help_declares_computer(capsys: pytest.CaptureFixture[str], snapshot: SnapshotAssertion) -> None:
    node = CLI_SURFACE["sessions"].subcommands["list"]

    assert any(flag.long == "--computer" for flag in node.flags)
    assert _maybe_show_help("sessions", ["list", "--help"]) is True
    assert capsys.readouterr().out == snapshot
