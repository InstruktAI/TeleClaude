"""Claude hook adapter."""

from __future__ import annotations


def _passthrough(data: dict[str, object]) -> dict[str, object]:
    return dict(data)


def normalize_payload(event_type: str, data: dict[str, object]) -> dict[str, object]:
    return _passthrough(data)
