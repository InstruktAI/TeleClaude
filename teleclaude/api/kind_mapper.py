"""v1 kind → canonical kind mapper for workflow.todo.created events."""

from __future__ import annotations

from teleclaude.core.next_machine.kinds import KIND_BUG, KIND_CHANGE, KIND_FEATURE, canonical_kind

__all__ = ["KIND_BUG", "KIND_CHANGE", "KIND_FEATURE", "map_v1_kind_to_canonical"]


def map_v1_kind_to_canonical(v1_kind: str | None) -> str:
    """Map any historical or current kind to the canonical {feature, change, bug}."""
    return canonical_kind(v1_kind)
