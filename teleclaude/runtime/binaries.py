"""Runtime binary resolution policy.

These paths are internal platform policy, not user-configurable settings.
"""

from __future__ import annotations

import os
import sys
from functools import cache
from pathlib import Path
from typing import Final

from teleclaude.agent_registry import AGENT_REGISTRY, AgentName

_MACOS_TMUX_BINARY = Path.home() / "Applications" / "TmuxLauncher.app" / "Contents" / "MacOS" / "tmux-launcher"
_UNIX_TMUX_BINARY = "tmux"
# How the macOS tmux launcher selects the tmux it runs, in its order: an override, the fixed candidates, then PATH.
# The launcher is generated from these values (project_setup.launcher_signing), so both select alike.
TMUX_LAUNCHER_OVERRIDE_KEYS: Final = ("TMUX_LAUNCHER_TARGET", "TMUX_BINARY")
TMUX_LAUNCHER_CANDIDATES: Final = ("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux", "/usr/bin/tmux")
_PATH_VARIABLE: Final = "PATH"


def _is_macos() -> bool:
    return sys.platform == "darwin"


def resolve_tmux_binary() -> str:
    """Resolve tmux binary by platform."""
    if _is_macos():
        return str(_MACOS_TMUX_BINARY)
    return _UNIX_TMUX_BINARY


@cache
def resolve_tmux_query_binary(configured: str) -> str:
    """The binary for a read that only queries the running tmux server.

    The macOS launcher resolves to the tmux it runs, selected as the launcher selects it; any other
    configured binary, or a launcher whose target cannot be found, is used as it is.
    """
    if configured != str(_MACOS_TMUX_BINARY):
        return configured
    environment = os.environ  # guard: direct-env-read - allowed: ambient host or terminal state
    for key in TMUX_LAUNCHER_OVERRIDE_KEYS:
        override = environment.get(key)
        if override and os.access(override, os.X_OK):
            return override
    for candidate in TMUX_LAUNCHER_CANDIDATES:
        if os.access(candidate, os.X_OK):
            return candidate
    for directory in environment.get(_PATH_VARIABLE, "").split(os.pathsep):
        candidate = os.path.join(directory, _UNIX_TMUX_BINARY)
        if directory and os.access(candidate, os.X_OK):
            return candidate
    return configured


def resolve_agent_binary(agent: str) -> str:
    """Resolve agent binary by platform.

    Args:
        agent: Canonical agent key (claude, gemini, codex, deepseek)
    """
    key = agent.strip().lower()
    try:
        name = AgentName(key)
    except ValueError:
        raise ValueError(f"Unknown agent '{agent}'") from None
    executable = AGENT_REGISTRY[name].executable
    if _is_macos() and executable.macos_launch_binary is not None:
        return str(
            Path.home()
            / "Applications"
            / executable.macos_launcher_app
            / "Contents"
            / "MacOS"
            / executable.macos_launch_binary
        )
    return executable.unix_binary
