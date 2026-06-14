"""Functional coverage for process-janitor event registration."""

from __future__ import annotations

import sys
from io import StringIO
from typing import cast

import pytest

from teleclaude.cli import telec as telec_cli
from teleclaude.events import build_default_catalog
from teleclaude.events import producer as producer_mod
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude.events.producer import EventProducer, configure_producer, emit_event

pytestmark = pytest.mark.functional

_EVENT_TYPE = "system.process.reaped"
_EVENT_DOMAIN = "system"
_EVENT_SOURCE = "process-janitor"
_PAYLOAD_FIELDS = frozenset(
    {
        "pid",
        "signature_id",
        "signature_name",
        "reason",
        "observe_only",
        "owner",
        "lease_expires_at",
    }
)


class _CapturingProducer:
    def __init__(self) -> None:
        self.envelope: EventEnvelope | None = None

    async def emit(self, envelope: EventEnvelope) -> str:
        self.envelope = envelope
        return "1-0"


def test_default_catalog_registers_process_reap_event_without_duplicates() -> None:
    """The built-in event catalog includes the process reap event."""
    schema = build_default_catalog().get(_EVENT_TYPE)

    assert schema is not None
    assert schema.default_level is EventLevel.OPERATIONAL
    assert schema.default_visibility is EventVisibility.LOCAL
    assert schema.domain == _EVENT_DOMAIN
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True
    assert set(schema.lifecycle.meaningful_fields) == _PAYLOAD_FIELDS


def test_events_list_surfaces_process_reap_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """The public events-list boundary surfaces the process reap event."""
    out = StringIO()
    monkeypatch.setattr(sys, "argv", ["telec", "events", "list", "--domain", "system"])
    monkeypatch.setattr("sys.stdout", out)

    telec_cli.main()

    event_types = {line[:55].strip() for line in out.getvalue().splitlines()[2:]}
    assert _EVENT_TYPE in event_types


@pytest.mark.asyncio
async def test_reap_event_emit_preserves_observable_payload_fields() -> None:
    """A process reap emit carries the fields operators need to diagnose the reap."""
    schema = build_default_catalog().get(_EVENT_TYPE)
    assert schema is not None
    assert schema.lifecycle is not None
    payload = {field: field for field in schema.lifecycle.meaningful_fields}
    producer = _CapturingProducer()
    previous = producer_mod._PRODUCER_STATE["producer"]
    configure_producer(cast(EventProducer, producer))

    try:
        entry_id = await emit_event(
            schema.event_type,
            source=_EVENT_SOURCE,
            level=schema.default_level,
            domain=schema.domain,
            visibility=schema.default_visibility,
            payload=payload,
        )
    finally:
        producer_mod._PRODUCER_STATE["producer"] = previous

    assert entry_id
    assert producer.envelope is not None
    restored = EventEnvelope.from_stream_dict(producer.envelope.to_stream_dict())
    assert restored.event == schema.event_type
    assert restored.source == _EVENT_SOURCE
    assert restored.level is schema.default_level
    assert restored.domain == schema.domain
    assert restored.visibility is schema.default_visibility
    assert set(restored.payload) == _PAYLOAD_FIELDS
