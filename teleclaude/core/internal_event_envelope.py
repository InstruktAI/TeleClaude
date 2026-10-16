"""Internal event bus envelope — the entry shape of the internal event stream.

Internal bus envelopes are not platform stream events: they state no subject and no
home. The stream is read across computers, so its entries keep exactly the keys older
computers read, with the platform-event facts they never carried fixed at their
earlier values.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from teleclaude.core.models import JsonDict
from teleclaude.events.envelope import EventLevel, EventVisibility, occurrence_id
from teleclaude.events.wire import StreamEntry

#: Wire generation of the internal event stream.
INTERNAL_STREAM_VERSION: int = 5
INTERNAL_EVENT_STREAM = "teleclaude:internal-events"

_EMPTY = ""
_NO_HOME = "none"
_INTERNAL_DOMAIN = "internal"


class InternalEventEnvelope(BaseModel):
    """One internal bus event as it travels on the internal event stream."""

    event: str
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    source: str
    originating_computer: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    idempotency_key: str | None = None
    visibility: EventVisibility = EventVisibility.LOCAL
    payload: JsonDict = Field(default_factory=dict)

    def to_stream_dict(self) -> dict[str, str]:
        """Serialize to the flat string dict the internal stream carries."""
        return {
            "event": self.event,
            "event_id": self.event_id,
            "version": str(INTERNAL_STREAM_VERSION),
            "source": self.source,
            "originating_computer": self.originating_computer or _EMPTY,
            "originating_session_id": _EMPTY,
            "origin_home": _EMPTY,
            "subject": _NO_HOME,
            "subject_owner": _NO_HOME,
            "timestamp": self.timestamp.isoformat(),
            "idempotency_key": self.idempotency_key or _EMPTY,
            "level": str(int(EventLevel.WORKFLOW)),
            "domain": _INTERNAL_DOMAIN,
            "entity": _EMPTY,
            "description": _EMPTY,
            "visibility": self.visibility.value,
            "payload": json.dumps(self.payload),
            "actions": _EMPTY,
            "human_action": _EMPTY,
            "terminal_when": _EMPTY,
            "resolution_shape": _EMPTY,
        }

    @classmethod
    def from_stream_dict(cls, data: StreamEntry, *, entry_id: str | None = None) -> InternalEventEnvelope:
        """Deserialize from an internal stream entry; keys this envelope does not use are ignored."""
        entry = {_text(key): _text(value) for key, value in data.items()}
        stable_id = entry.get("event_id") or (
            occurrence_id("internal-stream-entry", entry_id) if entry_id is not None else str(uuid4())
        )
        return cls(
            event=entry["event"],
            event_id=stable_id,
            source=entry["source"],
            originating_computer=entry.get("originating_computer") or None,
            timestamp=datetime.fromisoformat(entry["timestamp"]),
            idempotency_key=entry.get("idempotency_key") or None,
            visibility=EventVisibility(entry.get("visibility", EventVisibility.LOCAL.value)),
            payload=json.loads(entry["payload"]) if entry.get("payload") else {},
        )


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value
