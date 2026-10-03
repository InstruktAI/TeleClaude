"""Pure matching rules for agent event subscriptions."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import JsonValue

from teleclaude.events.envelope import (
    EventEnvelope,
    EventHomeKind,
    EventHomeRef,
    EventOwnerKind,
    EventOwnerRef,
    EventVisibility,
)

_POSITION_SEPARATOR = "-"
_INVALID_STREAM_POSITION_ERROR = "invalid Redis stream position"


def stream_position_key(position: str) -> tuple[int, int]:
    """Convert a Redis stream position to its numeric ordering key."""
    milliseconds, separator, sequence = position.partition(_POSITION_SEPARATOR)
    if not separator:
        raise ValueError(_INVALID_STREAM_POSITION_ERROR)
    return int(milliseconds), int(sequence)


def is_after_created_position(entry_id: str, created_position: str) -> bool:
    """Whether one stream entry was appended after the subscription was created."""
    return stream_position_key(entry_id) > stream_position_key(created_position)


def matches_narrowing(payload: Mapping[str, JsonValue], narrowing: Mapping[str, JsonValue]) -> bool:
    """Compare each declared narrowing value using JSON value equality."""
    return all(field in payload and _json_values_equal(payload[field], value) for field, value in narrowing.items())


def matches_visibility(envelope: EventEnvelope, computer_name: str) -> bool:
    """Apply the event catalog's visibility contract on the receiving computer."""
    if envelope.visibility is EventVisibility.LOCAL:
        return envelope.originating_computer == computer_name
    return envelope.visibility in {EventVisibility.CLUSTER, EventVisibility.PUBLIC}


def matches_company(company: str | None, envelope: EventEnvelope) -> bool:
    """Keep a company session within its company's event subjects."""
    if company is None:
        return True
    subject = envelope.subject
    if isinstance(subject, EventHomeRef) and subject.kind is EventHomeKind.COMPANY:
        return subject.instance == company
    return (
        isinstance(subject, EventHomeRef)
        and subject.kind is EventHomeKind.PROJECT
        and isinstance(envelope.subject_owner, EventOwnerRef)
        and envelope.subject_owner.kind is EventOwnerKind.COMPANY
        and envelope.subject_owner.instance == company
    )


def _json_values_equal(left: JsonValue, right: JsonValue) -> bool:
    """Compare JSON values recursively while keeping booleans distinct from numbers."""
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, str) or isinstance(right, str):
        return isinstance(left, str) and isinstance(right, str) and left == right
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right)
            and all(_json_values_equal(left_item, right_item) for left_item, right_item in zip(left, right))
        )
    if isinstance(left, dict) or isinstance(right, dict):
        return (
            isinstance(left, dict)
            and isinstance(right, dict)
            and left.keys() == right.keys()
            and all(_json_values_equal(left[key], right[key]) for key in left)
        )
    return False
