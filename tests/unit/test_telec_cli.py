"""Tests for telec CLI session-management behavior."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from teleclaude.cli import telec
from teleclaude.cli.api_client import APIError
from teleclaude.cli.models import CreateSessionResult


def test_attach_tmux_session_switches_inside_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    called: Dict[str, Any] = {}

    def fake_run(args: list[str], check: bool = False) -> None:  # noqa: ARG001 - signature match
        called["args"] = args

    monkeypatch.setenv("TMUX", "1")
    monkeypatch.setattr(telec.subprocess, "run", fake_run)

    telec._attach_tmux_session("tc_999")

    assert called["args"][:2] == [telec.config.computer.tmux_binary, "switch-client"]


def test_attach_tmux_session_attaches_outside_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    called: Dict[str, tuple[str, ...]] = {}

    def fake_execlp(*args: str) -> None:
        called["args"] = args

    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setattr(telec.os, "execlp", fake_execlp)

    telec._attach_tmux_session("tc_888")

    assert called["args"][1:] == (telec.config.computer.tmux_binary, "attach-session", "-t", "tc_888")


def test_revive_session_attaches_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    called: Dict[str, str] = {}

    async def fake_revive(_session_id: str) -> CreateSessionResult:
        return CreateSessionResult(status="success", session_id="sess-1", tmux_session_name="tc_revived", agent="codex")

    async def fake_kick(_session_id: str) -> bool:
        called["kick"] = "1"
        return True

    def fake_attach(name: str) -> None:
        called["name"] = name

    monkeypatch.setattr(telec, "_revive_session_via_api", fake_revive)
    monkeypatch.setattr(telec, "_send_revive_enter_via_api", fake_kick)
    monkeypatch.setattr(telec, "_attach_tmux_session", fake_attach)

    telec._revive_session("sess-1", attach=True)

    assert called["kick"] == "1"
    assert called["name"] == "tc_revived"


def test_revive_session_does_not_attach_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    called: Dict[str, str] = {}

    async def fake_revive(_session_id: str) -> CreateSessionResult:
        return CreateSessionResult(status="success", session_id="sess-1", tmux_session_name="tc_revived", agent="codex")

    async def fake_kick(_session_id: str) -> bool:
        called["kick"] = "1"
        return True

    def fake_attach(name: str) -> None:
        called["name"] = name

    monkeypatch.setattr(telec, "_revive_session_via_api", fake_revive)
    monkeypatch.setattr(telec, "_send_revive_enter_via_api", fake_kick)
    monkeypatch.setattr(telec, "_attach_tmux_session", fake_attach)

    telec._revive_session("sess-1", attach=False)

    assert called["kick"] == "1"
    assert "name" not in called


def test_revive_session_warns_when_kick_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_revive(_session_id: str) -> CreateSessionResult:
        return CreateSessionResult(status="success", session_id="sess-1", tmux_session_name="tc_revived", agent="codex")

    async def fake_kick(_session_id: str) -> bool:
        raise APIError("kick failed")

    monkeypatch.setattr(telec, "_revive_session_via_api", fake_revive)
    monkeypatch.setattr(telec, "_send_revive_enter_via_api", fake_kick)

    telec._revive_session("sess-1", attach=False)

    out = capsys.readouterr().out
    assert "Revived session sess-1" in out
    assert "Warning: revive kick failed: kick failed" in out


def test_help_includes_notes_and_examples_for_all_subcommands() -> None:
    for cmd_name, cmd in telec.CLI_SURFACE.items():
        if not cmd.subcommands:
            continue
        for sub_name in cmd.subcommands:
            output = telec._usage(cmd_name, sub_name)
            assert "\nNotes:\n" in output
            assert "\nExamples:\n" in output


def test_help_includes_notes_and_examples_for_top_level_leaf_commands() -> None:
    for cmd_name, cmd in telec.CLI_SURFACE.items():
        if cmd.subcommands:
            continue
        output = telec._usage(cmd_name)
        assert "\nNotes:\n" in output
        assert "\nExamples:\n" in output


def test_version_command_prints_version_channel_and_commit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _Result:
        returncode = 0
        stdout = "ea8cc35\n"

    def fake_run(args: list[str], capture_output: bool, text: bool, check: bool) -> _Result:
        assert args == ["git", "rev-parse", "--short", "HEAD"]
        assert capture_output is True
        assert text is True
        assert check is False
        return _Result()

    monkeypatch.setattr(telec, "__version__", "1.0.0")
    monkeypatch.setattr(telec.subprocess, "run", fake_run)

    telec._handle_cli_command(["version"])

    output = capsys.readouterr().out.strip()
    assert output == "TeleClaude v1.0.0 (channel: alpha, commit: ea8cc35)"


def test_version_command_uses_unknown_commit_when_git_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(args: list[str], capture_output: bool, text: bool, check: bool) -> None:
        _ = (args, capture_output, text, check)
        raise OSError("git not found")

    monkeypatch.setattr(telec, "__version__", "1.0.0")
    monkeypatch.setattr(telec.subprocess, "run", fake_run)

    telec._handle_cli_command(["version"])

    output = capsys.readouterr().out.strip()
    assert output == "TeleClaude v1.0.0 (channel: alpha, commit: unknown)"
