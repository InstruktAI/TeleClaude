"""Tests for telec CLI quick-start behavior."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from teleclaude.cli import telec
from teleclaude.cli.api_client import APIError
from teleclaude.cli.models import CreateSessionResult


def test_quick_start_attaches_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    called: Dict[str, str] = {}

    async def fake_api(_agent: str, _mode: str, _prompt: str | None) -> CreateSessionResult:
        return CreateSessionResult(status="success", session_id="abc", tmux_session_name="tc_123")

    def fake_attach(name: str) -> None:
        called["name"] = name

    monkeypatch.setattr(telec, "_quick_start_via_api", fake_api)
    monkeypatch.setattr(telec, "_attach_tmux_session", fake_attach)

    telec._quick_start("claude", "slow", None)

    assert called["name"] == "tc_123"


def test_quick_start_reports_api_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    async def fake_api(_agent: str, _mode: str, _prompt: str | None) -> CreateSessionResult:
        raise APIError("boom")

    monkeypatch.setattr(telec, "_quick_start_via_api", fake_api)

    telec._quick_start("claude", "slow", None)

    assert "Error: boom" in capsys.readouterr().out


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
