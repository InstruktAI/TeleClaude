"""Runtime binary resolution policy.

These paths are internal platform policy, not user-configurable settings.
"""

from __future__ import annotations

import sys
from pathlib import Path

_MACOS_TMUX_BINARY = Path.home() / "Applications" / "TmuxLauncher.app" / "Contents" / "MacOS" / "tmux-launcher"
_MACOS_AGENT_BINARIES: dict[str, Path | str] = {
    "claude": Path.home() / "Applications" / "ClaudeLauncher.app" / "Contents" / "MacOS" / "claude-launcher",
    "gemini": "agy",
    "codex": Path.home() / "Applications" / "CodexLauncher.app" / "Contents" / "MacOS" / "codex-launcher",
    # Signed launcher bundle so macOS TCC permissions attach to a stable
    # identity (npm-global CLI paths move between installs).
    "deepseek": Path.home() / "Applications" / "DeepSeekLauncher.app" / "Contents" / "MacOS" / "deepseek-launcher",
}

_UNIX_TMUX_BINARY = "tmux"
_UNIX_AGENT_BINARIES: dict[str, str] = {
    "claude": "claude",
    "gemini": "agy",
    "codex": "codex",
    "deepseek": "dsh",
}


def _is_macos() -> bool:
    return sys.platform == "darwin"


def resolve_tmux_binary() -> str:
    """Resolve tmux binary by platform."""
    if _is_macos():
        return str(_MACOS_TMUX_BINARY)
    return _UNIX_TMUX_BINARY


def resolve_agent_binary(agent: str) -> str:
    """Resolve agent binary by platform.

    Args:
        agent: Canonical agent key (claude, gemini, codex)
    """
    key = agent.strip().lower()
    if key not in _UNIX_AGENT_BINARIES:
        raise ValueError(f"Unknown agent '{agent}'")
    if _is_macos():
        val = _MACOS_AGENT_BINARIES[key]
        return str(val) if isinstance(val, Path) else val
    return _UNIX_AGENT_BINARIES[key]
