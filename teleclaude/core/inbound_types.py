"""Closed vocabularies for durable inbound delivery and turn provenance."""

from enum import StrEnum


class InboundMessageType(StrEnum):
    """Accepted inbound payload kinds persisted by the durable queue."""

    TEXT = "text"
    VOICE = "voice"
    FILE = "file"
    REMINDER = "reminder"


class TurnPartKind(StrEnum):
    """Authorship classes for exact spans in a bound native turn."""

    LOCAL = "local"
    INJECTED_PEER = "injected_peer"
    INJECTED_REMINDER = "injected_reminder"
