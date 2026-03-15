from __future__ import annotations

from types import SimpleNamespace

import pytest

from teleclaude.cli.tui.pane_manager import ComputerInfo, TmuxPaneManager


@pytest.mark.unit
def test_build_attach_cmd_uses_local_tmux_binary_when_session_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = object.__new__(TmuxPaneManager)
    monkeypatch.setattr("teleclaude.cli.tui.pane_manager.config.computer", SimpleNamespace(tmux_binary="tmux-bin"))

    command = manager._build_attach_cmd("tc_demo")

    assert command.startswith("env -u TMUX TERM=tmux-256color tmux-bin -u ")
    assert "attach-session -t tc_demo" in command


@pytest.mark.unit
def test_build_attach_cmd_includes_ssh_and_appearance_env_for_remote_sessions() -> None:
    manager = object.__new__(TmuxPaneManager)
    manager._get_appearance_env = lambda: {"APPEARANCE_MODE": "dark", "TERMINAL_BG": "#000000"}
    computer = ComputerInfo(name="remote", is_local=False, user="alice", host="example.test", tmux_binary="tmux-r")

    command = manager._build_attach_cmd("tc_demo", computer)

    assert "ssh -t -A alice@example.test" in command
    assert "APPEARANCE_MODE=dark TERMINAL_BG=#000000 TERM=tmux-256color tmux-r -u" in command
    assert "attach-session -t tc_demo" in command


@pytest.mark.unit
def test_get_current_pane_id_prefers_tmux_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = object.__new__(TmuxPaneManager)
    monkeypatch.setenv("TMUX_PANE", "%42")
    manager._run_tmux = lambda *args: "%99"

    assert manager._get_current_pane_id() == "%42"


@pytest.mark.unit
def test_focus_pane_for_session_selects_known_panes_and_reports_missing_ones() -> None:
    manager = object.__new__(TmuxPaneManager)
    manager._in_tmux = True
    manager.state = SimpleNamespace(session_to_pane={"session-1": "%2"})
    calls: list[tuple[str, ...]] = []
    manager._run_tmux = lambda *args: calls.append(args) or ""

    assert manager.focus_pane_for_session("session-1") is True
    assert manager.focus_pane_for_session("missing") is False
    assert calls == [("select-pane", "-t", "%2")]
