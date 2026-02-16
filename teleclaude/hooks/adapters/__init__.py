"""Hook adapters for agent-specific normalization."""

from __future__ import annotations

from teleclaude.hooks.adapters.base import HookAdapter
from teleclaude.hooks.adapters.claude import ClaudeAdapter
from teleclaude.hooks.adapters.codex import CodexAdapter
from teleclaude.hooks.adapters.gemini import GeminiAdapter

__all__ = [
    "ClaudeAdapter",
    "CodexAdapter",
    "GeminiAdapter",
    "HookAdapter",
    "get_adapter",
]

_ADAPTERS: dict[str, HookAdapter] = {
    "claude": ClaudeAdapter(),
    "gemini": GeminiAdapter(),
    "codex": CodexAdapter(),
}


def get_adapter(agent: str) -> HookAdapter:
    """Get the hook adapter for an agent."""
    return _ADAPTERS[agent]
