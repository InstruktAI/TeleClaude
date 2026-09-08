"""Helper-only agent types.

``AgentName`` is re-exported from ``teleclaude.agent_registry``, a leaf module
with no internal dependencies — importing it here stays standalone. Only
``ThinkingMode`` is declared in this module, since it has no canonical
registry of its own.
"""

from enum import Enum

from teleclaude.agent_registry import AgentName as AgentName


class ThinkingMode(str, Enum):
    """Supported thinking modes."""

    FAST = "fast"
    MED = "med"
    SLOW = "slow"
    DEEP = "deep"
    DEFAULT = "default"

    @classmethod
    def from_str(cls, value: str) -> "ThinkingMode":
        """Parse a case-insensitive thinking mode into an enum member."""
        normalized = value.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"Unknown thinking_mode '{value}'")

    @classmethod
    def choices(cls) -> tuple[str, ...]:
        """Return the CLI choice values for supported thinking modes."""
        return tuple(member.value for member in cls)
