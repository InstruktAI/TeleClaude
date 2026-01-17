"""Unit tests for TUI appearance hook command."""

from teleclaude.cli.tui.app import _build_tmux_appearance_hook_cmd


def test_build_tmux_appearance_hook_cmd_targets_tui_session() -> None:
    """Ensure hook command signals the tc_tui pane process on appearance changes."""
    cmd = _build_tmux_appearance_hook_cmd("/opt/homebrew/bin/tmux")

    assert "@appearance_mode" in cmd
    assert "list-panes -t tc_tui" in cmd
    assert "teleclaude.cli.telec" in cmd
    assert "kill -USR1" in cmd
