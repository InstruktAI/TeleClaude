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
_RECORD_PAYLOAD_FIELD = "payload"
_PAYLOAD_TYPE_FIELD = "type"


class _ClaudeRecordType(StrEnum):
    """The Claude transcript record types that bear on whether a turn has ended."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    QUEUE_OPERATION = "queue-operation"


_TURN_OPENING_RECORD_TYPES = frozenset(
    {_ClaudeRecordType.USER, _ClaudeRecordType.ASSISTANT, _ClaudeRecordType.QUEUE_OPERATION}
)


class _CodexRecordType(StrEnum):
    """The Codex rollout record type that carries turn lifecycle events."""

    EVENT_MSG = "event_msg"


class _CodexLifecycleEvent(StrEnum):
    """The Codex ``event_msg`` payload types that open and close a turn."""

    TASK_STARTED = "task_started"
    TASK_COMPLETE = "task_complete"


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


def codex_turn_completion(entries: Sequence[JsonDict]) -> datetime | None:
    """Return when Codex's latest turn ended, or ``None`` while a turn is open.

    Codex writes a ``task_complete`` event once a turn ends, including a turn the
    provider failed (the payload then carries an ``error``), and ``task_started``
    ahead of the next. The failed turn emits no Stop hook, so this record is the
    only evidence it ended. A ``task_started`` after a completion means more work
    follows, so the completion no longer stands.
    """
    completion: datetime | None = None
    for entry in entries:
        if entry.get(_RECORD_TYPE_FIELD) != _CodexRecordType.EVENT_MSG:
            continue
        payload = entry.get(_RECORD_PAYLOAD_FIELD)
        if not isinstance(payload, dict):
            continue
        event = payload.get(_PAYLOAD_TYPE_FIELD)
        if event == _CodexLifecycleEvent.TASK_STARTED:
            completion = None
        elif event == _CodexLifecycleEvent.TASK_COMPLETE:
            timestamp = entry.get(_RECORD_TIMESTAMP_FIELD)
            completion = _parse_timestamp(timestamp) if isinstance(timestamp, str) else None
    return completion
