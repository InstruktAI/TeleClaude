"""Shared telec constants and the config context's lazy runtime accessor."""

from __future__ import annotations

from teleclaude.cli.session_auth import TUI_SESSION_ENV_KEY as TUI_ENV_KEY

TMUX_ENV_KEY = "TMUX"
TUI_SESSION_NAME = "tc_tui"

__all__ = ["TMUX_ENV_KEY", "TUI_ENV_KEY", "TUI_SESSION_NAME"]
