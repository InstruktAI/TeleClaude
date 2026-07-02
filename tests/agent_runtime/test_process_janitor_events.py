"""Functional coverage for process-janitor event registration."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any, cast

import pytest

from teleclaude.cli import telec as telec_cli
from teleclaude.core.db import Db
from teleclaude.events import build_default_catalog
from teleclaude.events import producer as producer_mod
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude.events.producer import EventProducer, configure_producer, emit_event
from teleclaude.services.process_janitor.matcher import (
    MatcherKind,
    ProcessDescriptor,
    ProcessJanitorPolicy,
    ProcessMatch,
)
from teleclaude.services.process_janitor.service import ProcessJanitorService, ProcessJanitorSettings

pytestmark = pytest.mark.functional

_EVENT_TYPE = "system.process.reaped"
_EVENT_DOMAIN = "system"
_EVENT_SOURCE = "process-janitor"
_REVALIDATION_SECONDS = 3600
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


def _service() -> ProcessJanitorService:
    return ProcessJanitorService(
        cast(Db, object()),
        ProcessJanitorSettings(
            scan_interval_seconds=60,
            default_signature_ttl_seconds=60,
            dry_run_default=True,
            reap_revalidation_seconds=_REVALIDATION_SECONDS,
        ),
        cast(Any, object()),
    )


def _match(*, pid: int, signature_id: str) -> ProcessMatch:
    return ProcessMatch(
        process=ProcessDescriptor(pid=pid, ppid=1, create_time=0.0, cmdline=("python",), uid=0),
        policy=ProcessJanitorPolicy(
            signature_id=signature_id,
            name=signature_id,
            matcher_kind=MatcherKind.PROCESS_SIGNATURE,
            matcher_params={},
            ttl_seconds=60,
            dry_run=True,
        ),
    )


async def _captured_idempotency_key(match: ProcessMatch, *, now: datetime) -> str | None:
    service = _service()
    producer = _CapturingProducer()
    previous = producer_mod._PRODUCER_STATE["producer"]
    configure_producer(cast(EventProducer, producer))

    try:
        await service._emit_reap_event(match, observe_only=True, now=now)
    finally:
        producer_mod._PRODUCER_STATE["producer"] = previous

    assert producer.envelope is not None
    return producer.envelope.idempotency_key


@pytest.mark.asyncio
async def test_reap_event_idempotency_key_matches_for_repeat_sighting_in_same_bucket() -> None:
    """Two emits for the same pid/signature within the same revalidation window share a key."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    match = _match(pid=100, signature_id="sig-a")

    first_key = await _captured_idempotency_key(match, now=now)
    second_key = await _captured_idempotency_key(match, now=now)

    assert first_key == second_key


@pytest.mark.asyncio
async def test_reap_event_idempotency_key_differs_across_signature_ids() -> None:
    """The same pid matched by a different signature gets a distinct idempotency key."""
    now = datetime(2026, 1, 1, tzinfo=UTC)

    key_a = await _captured_idempotency_key(_match(pid=100, signature_id="sig-a"), now=now)
    key_b = await _captured_idempotency_key(_match(pid=100, signature_id="sig-b"), now=now)

    assert key_a != key_b


@pytest.mark.asyncio
async def test_reap_event_idempotency_key_differs_across_revalidation_windows() -> None:
    """The same pid/signature one revalidation window later gets a distinct idempotency key."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    next_window = now + timedelta(seconds=_REVALIDATION_SECONDS)
    match = _match(pid=100, signature_id="sig-a")

    first_key = await _captured_idempotency_key(match, now=now)
    second_key = await _captured_idempotency_key(match, now=next_window)

    assert first_key != second_key
