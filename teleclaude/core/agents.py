"""Shared Agent metadata."""

from __future__ import annotations

from enum import Enum


class AgentName(str, Enum):
    """Known AI agent names."""

    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"

    @classmethod
    def from_str(cls, value: str) -> "AgentName":
        """Convert a string to AgentName, raising ValueError on unknown values."""
        normalized = value.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"Unknown agent '{value}'")
