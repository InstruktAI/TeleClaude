"""Runtime binary resolution policy.

These paths are internal platform policy, not user-configurable settings.
"""

from __future__ import annotations

import sys
from functools import cache
from pathlib import Path

from teleclaude.agent_registry import AGENT_REGISTRY, AgentName

_MACOS_TMUX_BINARY = Path.home() / "Applications" / "TmuxLauncher.app" / "Contents" / "MacOS" / "tmux-launcher"
_UNIX_TMUX_BINARY = "tmux"
# The multiplexer clients the macOS launcher itself runs, in the order it looks for them.
_MACOS_TMUX_CLIENTS = (Path("/opt/homebrew/bin/tmux"), Path("/usr/local/bin/tmux"))


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

    The server performs such a read with its own identity, so it needs no launcher: the macOS
    launcher resolves to the client it runs, and any other configured binary is used as it is.
    """
    if configured != str(_MACOS_TMUX_BINARY):
        return configured
    for client in _MACOS_TMUX_CLIENTS:
        if client.is_file():
            return str(client)
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
