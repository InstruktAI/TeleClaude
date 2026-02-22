"""Unit tests for TmuxPaneManager remote attach command."""

from __future__ import annotations

from teleclaude.cli.tui.pane_manager import ComputerInfo, TmuxPaneManager
from teleclaude.config import config


def test_remote_attach_uses_remote_tmux_binary(monkeypatch) -> None:
    manager = TmuxPaneManager()
    monkeypatch.setattr(config.computer, "tmux_binary", "/local/tmux-wrapper")

    info = ComputerInfo(
        name="remote",
        is_local=False,
        user="me",
        host="remote.local",
        tmux_binary="/remote/tmux-wrapper",
    )

    cmd = manager._build_attach_cmd("tc_123", info)

    assert "/remote/tmux-wrapper -u" in cmd
    assert "set-option -t tc_123 status off" in cmd
    assert "attach-session -t tc_123" in cmd


def test_remote_attach_defaults_to_tmux_when_missing(monkeypatch) -> None:
    manager = TmuxPaneManager()
    monkeypatch.setattr(config.computer, "tmux_binary", "/local/tmux-wrapper")

    info = ComputerInfo(
        name="remote",
        is_local=False,
        user="me",
        host="remote.local",
        tmux_binary=None,
    )

    cmd = manager._build_attach_cmd("tc_456", info)

    assert "tmux -u" in cmd
    assert "set-option -t tc_456 status off" in cmd
    assert "attach-session -t tc_456" in cmd
    assert "/local/tmux-wrapper" not in cmd
