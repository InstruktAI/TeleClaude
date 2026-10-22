"""Presentation-owned decisions about the lifetime of human-facing messages."""

from teleclaude.core.origins import InputOrigin


def retains_human_conversation_input(origin: InputOrigin) -> bool:
    """Return whether input from this origin remains visible as conversation history."""
    return origin is InputOrigin.DISCORD
