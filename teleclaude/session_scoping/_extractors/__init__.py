"""Agent-native extractors for session scoping."""

from __future__ import annotations

from ._common import ExtractorFunction, extract_structured_paths_from_timeline
from .claude import collect_claude_paths
from .codex import collect_codex_paths
from .gemini import collect_gemini_paths

__all__ = [
    "collect_claude_paths",
    "collect_codex_paths",
    "collect_gemini_paths",
    "extract_structured_paths_from_timeline",
    "resolve_extractor",
]


def resolve_extractor(agent_name: str) -> ExtractorFunction:
    """Return the agent-native extractor for the provided agent."""
    normalized = agent_name.strip().lower()
    if normalized == "codex":
        return collect_codex_paths
    if normalized == "claude":
        return collect_claude_paths
    if normalized in ("gemini", "agy"):
        return collect_gemini_paths
    raise ValueError(f"Unknown agent '{agent_name}'")
