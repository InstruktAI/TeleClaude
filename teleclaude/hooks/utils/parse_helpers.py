"""Shared parsing helpers for hook adapters."""

from __future__ import annotations


def coerce_str(value: object) -> str | None:
    """Normalize a value to a non-empty string, or None."""
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def get_str(data: dict[str, object], key: str) -> str | None:  # noqa: loose-dict - Agent hook data
    """Fetch a string from a specific top-level key (no nesting)."""
    return coerce_str(data.get(key))
