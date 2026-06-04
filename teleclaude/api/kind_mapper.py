"""v1 kind → canonical kind mapper for workflow.todo.created events."""

from __future__ import annotations

from teleclaude.types.todo_kind import (
    PREPARE_LANE_KINDS,
    TODO_KIND_BUG,
    TODO_KIND_FEATURE,
    TODO_KIND_MIGRATION,
    TODO_KIND_PREPPED,
    TODO_KIND_REFACTOR,
    TODO_KIND_TODO,
)

KIND_FEATURE = TODO_KIND_FEATURE
KIND_BUG = TODO_KIND_BUG
KIND_REFACTOR = TODO_KIND_REFACTOR
KIND_MIGRATION = TODO_KIND_MIGRATION
KIND_TODO = TODO_KIND_TODO
KIND_PREPPED = TODO_KIND_PREPPED

_CANONICAL_KINDS = PREPARE_LANE_KINDS | {KIND_BUG, KIND_PREPPED}


def map_v1_kind_to_canonical(v1_kind: str | None) -> str:
    """Map a v1 todo kind to its canonical kind for event payloads.

    Mapping rules:
      None | ""                              → "feature"
      "bug"                                  → "bug"
      "prepped"                              → "prepped" (routes /next-work bypass lane)
      "draft"                                → "feature"
      canonical (feature|refactor|migration|todo|bug) → passthrough
    """
    if not v1_kind:
        return KIND_FEATURE
    if v1_kind in _CANONICAL_KINDS:
        return v1_kind
    return KIND_FEATURE
