"""Shared helpers for launching sessions from the TUI."""

from __future__ import annotations

import curses
import os
import subprocess

from teleclaude.cli.models import CreateSessionResult
from teleclaude.config import config


def attach_tmux_session(tmux_session_name: str | None, stdscr: object) -> bool:
    """Attach a tmux session in a right-side split pane.

    Returns True if a split was opened.
    """
    if not tmux_session_name:
        return False

    if not os.environ.get("TMUX"):
        return False

    curses.def_prog_mode()
    curses.endwin()
    tmux = config.computer.tmux_binary
    subprocess.run(
        [tmux, "split-window", "-h", "-p", "60", f"{tmux} attach -t {tmux_session_name}"],
        check=False,
    )
    curses.reset_prog_mode()
    stdscr.refresh()  # type: ignore[attr-defined]
    return True


def attach_tmux_from_result(result: CreateSessionResult, stdscr: object) -> bool:
    """Attach tmux session from create_session API result."""
    tmux_session_name = result.tmux_session_name
    return attach_tmux_session(tmux_session_name, stdscr) if tmux_session_name else False
