"""Shared constants and config proxy for the telec package."""

from __future__ import annotations

from typing import Any

TMUX_ENV_KEY = "TMUX"
TUI_ENV_KEY = "TELEC_TUI_SESSION"
TUI_AUTH_EMAIL_ENV_KEY = "TELEC_AUTH_EMAIL"
TUI_SESSION_NAME = "tc_tui"


class _ConfigProxy:
    """Lazily resolve runtime config on first attribute access.

    This keeps low-dependency commands (for example `telec todo demo validate`)
    usable even when runtime config loading would fail.
    """

    def __getattr__(self, name: str) -> Any:
        from teleclaude.config import config as runtime_config

        return getattr(runtime_config, name)


config = _ConfigProxy()
