"""Helper-only agent types (standalone, no external deps)."""

from enum import Enum


class AgentName(str, Enum):
    """Supported agent names."""

    CLAUDE = "claude"
    GEMINI = "gemini"
    CODEX = "codex"

    @classmethod
    def from_str(cls, value: str) -> "AgentName":
        normalized = value.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"Unknown agent '{value}'")

    @classmethod
    def choices(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)


class ThinkingMode(str, Enum):
    """Supported thinking modes."""

    FAST = "fast"
    MED = "med"
    SLOW = "slow"
    DEEP = "deep"

    @classmethod
    def from_str(cls, value: str) -> "ThinkingMode":
        normalized = value.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"Unknown thinking_mode '{value}'")

    @classmethod
    def choices(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)
