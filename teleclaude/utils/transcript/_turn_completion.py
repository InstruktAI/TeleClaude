"""Interpret a runtime's raw transcript tail as the time its latest turn ended."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from teleclaude.core.models import JsonDict

from ._utils import _parse_timestamp

TURN_COMPLETION_TAIL_ENTRIES = 64
"""Raw tail records read per scan; records after a completion are a handful of metadata lines."""

_RECORD_TYPE_FIELD = "type"
_RECORD_SUBTYPE_FIELD = "subtype"
_RECORD_SIDECHAIN_FIELD = "isSidechain"
_RECORD_TIMESTAMP_FIELD = "timestamp"
_TURN_DURATION_SUBTYPE = "turn_duration"


class _ClaudeRecordType(StrEnum):
    """The Claude transcript record types that bear on whether a turn has ended."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    QUEUE_OPERATION = "queue-operation"


_TURN_OPENING_RECORD_TYPES = frozenset(
    {_ClaudeRecordType.USER, _ClaudeRecordType.ASSISTANT, _ClaudeRecordType.QUEUE_OPERATION}
)


def claude_turn_completion(entries: Sequence[JsonDict]) -> datetime | None:
    """Return when Claude's latest turn ended, or ``None`` while a turn is open or queued.

    Claude writes a main-chain ``turn_duration`` record once a turn's loop and
    its Stop hooks have finished; a checkpoint continuation never gets one. Any
    main-chain record that opens a turn, or a queued prompt, after it means more
    work follows, so the completion no longer stands.
    """
    completion: datetime | None = None
    for entry in entries:
        if entry.get(_RECORD_SIDECHAIN_FIELD) is True:
            continue
        record_type = entry.get(_RECORD_TYPE_FIELD)
        if record_type in _TURN_OPENING_RECORD_TYPES:
            completion = None
        elif record_type == _ClaudeRecordType.SYSTEM and entry.get(_RECORD_SUBTYPE_FIELD) == _TURN_DURATION_SUBTYPE:
            timestamp = entry.get(_RECORD_TIMESTAMP_FIELD)
            completion = _parse_timestamp(timestamp) if isinstance(timestamp, str) else None
    return completion
