"""Hook adapters for agent-specific normalization."""

from __future__ import annotations

from teleclaude.hooks.adapters.agy import AgyAdapter
from teleclaude.hooks.adapters.base import HookAdapter
from teleclaude.hooks.adapters.claude import ClaudeAdapter
from teleclaude.hooks.adapters.codex import CodexAdapter
from teleclaude.hooks.adapters.dsh import DshAdapter

__all__ = [
    "AgyAdapter",
    "ClaudeAdapter",
    "CodexAdapter",
    "DshAdapter",
    "get_adapter",
]

_ADAPTERS: dict[str, HookAdapter] = {
    "claude": ClaudeAdapter(),
    "agy": AgyAdapter(),
    "gemini": AgyAdapter(),
    "codex": CodexAdapter(),
    "deepseek": DshAdapter(),
}


def get_adapter(agent: str) -> HookAdapter:
    """Get the hook adapter for an agent."""
    return _ADAPTERS[agent]
