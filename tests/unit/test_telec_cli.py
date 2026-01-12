"""Unit tests for telec CLI behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from teleclaude.cli import telec
from teleclaude.config import config


def test_main_restarts_existing_tui_session() -> None:
    """telec should kill existing tc_tui and start a fresh session."""
    tmux = config.computer.tmux_binary
    run_result = SimpleNamespace(returncode=0)
    mock_execlp = Mock(side_effect=SystemExit)

    with (
        patch("teleclaude.cli.telec.os.environ", {}),
        patch("teleclaude.cli.telec.subprocess.run", return_value=run_result) as mock_run,
        patch("teleclaude.cli.telec.os.execlp", mock_execlp),
    ):
        try:
            telec.main()
        except SystemExit:
            pass

    assert mock_run.mock_calls == [
        (([tmux, "has-session", "-t", "tc_tui"],), {"capture_output": True}),
        (
            ([tmux, "kill-session", "-t", "tc_tui"],),
            {"check": False, "capture_output": True},
        ),
    ]
    mock_execlp.assert_called_once_with(tmux, tmux, "new-session", "-s", "tc_tui", "-e", "TELEC_TUI_SESSION=1", "telec")


def test_main_starts_new_tui_session_when_missing() -> None:
    """telec should create a fresh tc_tui session when none exists."""
    tmux = config.computer.tmux_binary
    run_result = SimpleNamespace(returncode=1)
    mock_execlp = Mock(side_effect=SystemExit)

    with (
        patch("teleclaude.cli.telec.os.environ", {}),
        patch("teleclaude.cli.telec.subprocess.run", return_value=run_result) as mock_run,
        patch("teleclaude.cli.telec.os.execlp", mock_execlp),
    ):
        try:
            telec.main()
        except SystemExit:
            pass

    assert mock_run.mock_calls == [(([tmux, "has-session", "-t", "tc_tui"],), {"capture_output": True})]
    mock_execlp.assert_called_once_with(tmux, tmux, "new-session", "-s", "tc_tui", "-e", "TELEC_TUI_SESSION=1", "telec")


def test_maybe_kill_tui_session_skips_without_env() -> None:
    """No-op when telec did not create the session."""
    with patch("teleclaude.cli.telec.os.environ", {}), patch("teleclaude.cli.telec.subprocess.run") as mock_run:
        telec._maybe_kill_tui_session()

    mock_run.assert_not_called()


def test_maybe_kill_tui_session_kills_tc_tui() -> None:
    """Kill tc_tui when telec created the session."""
    tmux = config.computer.tmux_binary
    display_result = SimpleNamespace(stdout="tc_tui\n", returncode=0)
    with (
        patch("teleclaude.cli.telec.os.environ", {"TELEC_TUI_SESSION": "1", "TMUX": "1"}),
        patch("teleclaude.cli.telec.subprocess.run", side_effect=[display_result, display_result]) as mock_run,
    ):
        telec._maybe_kill_tui_session()

    assert mock_run.mock_calls == [
        (
            ([tmux, "display-message", "-p", "#S"],),
            {"capture_output": True, "text": True, "check": False},
        ),
        (([tmux, "kill-session", "-t", "tc_tui"],), {"check": False, "capture_output": True}),
    ]


def test_ensure_tmux_mouse_on_skips_without_tmux() -> None:
    """No-op when not inside tmux."""
    with patch("teleclaude.cli.telec.os.environ", {}), patch("teleclaude.cli.telec.subprocess.run") as mock_run:
        telec._ensure_tmux_mouse_on()

    mock_run.assert_not_called()


def test_ensure_tmux_mouse_on_sets_window_option() -> None:
    """Enable tmux mouse for current window."""
    tmux = config.computer.tmux_binary
    with (
        patch("teleclaude.cli.telec.os.environ", {"TMUX": "1"}),
        patch("teleclaude.cli.telec.subprocess.run") as mock_run,
    ):
        telec._ensure_tmux_mouse_on()

    mock_run.assert_called_once_with(
        [tmux, "set-option", "-w", "mouse", "on"],
        check=False,
        capture_output=True,
    )
