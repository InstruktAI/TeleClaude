"""Closed vocabularies for durable inbound delivery and turn provenance."""

from enum import StrEnum


class InboundMessageType(StrEnum):
    """Accepted inbound payload kinds persisted by the durable queue."""

    TEXT = "text"
    VOICE = "voice"
    FILE = "file"
    REMINDER = "reminder"
