"""The explicit project-owner states an event's home can carry that are not registry references."""

from __future__ import annotations

from enum import StrEnum


class EventHomeOwnerMarker(StrEnum):
    """Explicit project-owner states that are not registry references."""

    NONE = "none"
    OWNERLESS = "ownerless"
    UNRESOLVED = "unresolved"
