"""Project-facing scope for configured jobs."""

from enum import StrEnum


class JobScope(StrEnum):
    """A project's relationship to one visible job."""

    LOCAL = "local"
    SUBSCRIBED = "subscribed"
    AVAILABLE = "available"
