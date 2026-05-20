"""v1 kind → canonical kind mapper for workflow.todo.created events."""

from __future__ import annotations

KIND_FEATURE = "feature"
KIND_BUG = "bug"
KIND_REFACTOR = "refactor"
KIND_MIGRATION = "migration"

_CANONICAL_KINDS = {KIND_FEATURE, KIND_REFACTOR, KIND_MIGRATION, KIND_BUG}

_V1_TO_CANONICAL: dict[str, str] = {
    KIND_BUG: KIND_BUG,
}


def map_v1_kind_to_canonical(v1_kind: str | None) -> str:
    """Map a v1 todo kind to its canonical kind for event payloads.

    Mapping rules:
      None | "" → "feature"
      "bug"     → "bug"
      "prepped" → "feature"
      "draft"   → "feature"
      canonical ("feature"|"refactor"|"migration") → passthrough
    """
    if not v1_kind:
        return KIND_FEATURE
    if v1_kind in _CANONICAL_KINDS:
        return v1_kind
    return _V1_TO_CANONICAL.get(v1_kind, KIND_FEATURE)
