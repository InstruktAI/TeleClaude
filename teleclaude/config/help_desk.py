"""Enable a home's help desk in its declaration."""

from __future__ import annotations

from collections.abc import Mapping

HELP_DESK_KEY = "help_desk"
_ENABLED_KEY = "enabled"


def with_help_desk_enabled(document: Mapping[str, object]) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    """Return ``document`` with its help desk enabled and every other value kept."""
    current = document.get(HELP_DESK_KEY)
    section = dict(current) if isinstance(current, Mapping) else {}
    section[_ENABLED_KEY] = True
    return {**document, HELP_DESK_KEY: section}


__all__ = ["HELP_DESK_KEY", "with_help_desk_enabled"]
