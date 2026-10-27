"""Closed vocabularies for durable inbound delivery and turn provenance."""

from enum import StrEnum


class InboundMessageType(StrEnum):
    """Accepted inbound payload kinds persisted by the durable queue."""

    TEXT = "text"
    VOICE = "voice"
    FILE = "file"
    REMINDER = "reminder"


class InboundBindingDisposition(StrEnum):
    """Terminal states for delivered rows that cannot acquire a turn binding."""

    LEGACY_PRE_CUTOVER = "legacy_pre_cutover"
    INPUT_CONFLICT = "input_conflict"


GITHUB_ACTOR_ID_PREFIX = "github:"


class TurnPartKind(StrEnum):
    """Authorship classes for the ordered spans of one bound native turn."""

    LOCAL = "local"
    CALLER = "caller"
    PEER = "peer"
    GITHUB = "github"
