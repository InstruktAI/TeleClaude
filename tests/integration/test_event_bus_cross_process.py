"""Integration specs for ``event-bus-redis-migration`` cross-role delivery.

These specs pin the cross-role and inherited-reliability behaviors of the
Redis-Streams-backed ``EventBus`` adapter. All specs run against a Redis fake
that preserves consumer-group cursor and PEL semantics — covering the
work-sharing, cross-role-subscriber, and stale-PEL-reclaim contracts without
spawning a real subprocess or requiring a live Redis instance.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict, cast

import pytest

from teleclaude.core.agent_coordinator import _coordinator as coordinator_module
from teleclaude.core.agent_coordinator._coordinator import AgentCoordinator
from teleclaude.core.agents import AgentName
from teleclaude.core.event_bus import EventBus
from teleclaude.core.events import ErrorEventContext, SessionLifecycleContext, TeleClaudeEvents
from teleclaude.events.envelope import EventEnvelope
from teleclaude.utils.transcript import _iterators as transcript_iterators


class _PendingEntry(TypedDict):
    message_id: bytes
    consumer: bytes
    time_since_delivered: int
    times_delivered: int


@dataclass
class _StreamEntry:
    entry_id: str
    data: dict[str, str]


@dataclass
class _GroupCursor:
    """Per-consumer-group cursor + PEL, modeled after Redis Streams."""

    delivered_index: int = 0
    pending: dict[str, str] = field(default_factory=dict)  # entry_id -> consumer name
    pending_idle_ms: dict[str, int] = field(default_factory=dict)


class _RedisStreamFake:
    """Minimal Redis Streams fake with consumer-group cursor + PEL semantics.

    Per-group cursors give cross-group fan-out. Within a group, only one
    consumer at a time may read the next entry (work-queue). XACK clears
    PEL entries.
    """

    def __init__(self) -> None:
        self._streams: dict[str, list[_StreamEntry]] = {}
        self._groups: dict[str, dict[str, _GroupCursor]] = {}  # stream -> group -> cursor
        self._next_id = 0

    async def xadd(self, stream: str, data: dict[str, str], **kwargs: Any) -> bytes:
        del kwargs  # accept maxlen and other production options without using
        self._streams.setdefault(stream, [])
        self._next_id += 1
        entry = _StreamEntry(entry_id=f"{self._next_id}-0", data=dict(data))
        self._streams[stream].append(entry)
        return entry.entry_id.encode()

    async def xgroup_create(self, stream: str, group: str, **kwargs: Any) -> None:
        del kwargs  # accept id, mkstream without using
        self._groups.setdefault(stream, {})
        if group in self._groups[stream]:
            raise Exception("BUSYGROUP Consumer Group name already exists")
        self._groups[stream][group] = _GroupCursor()

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        count: int = 10,
        block: int | None = None,
    ) -> list[tuple[bytes, list[tuple[bytes, dict[str, str]]]]]:
        del count, block  # fake delivers all available entries; production batching/blocking is not modeled
        out: list[tuple[bytes, list[tuple[bytes, dict[str, str]]]]] = []
        for stream_name in streams:
            entries = self._streams.get(stream_name, [])
            cursor = self._groups.get(stream_name, {}).get(group)
            if cursor is None:
                continue
            if cursor.delivered_index >= len(entries):
                continue
            entry = entries[cursor.delivered_index]
            cursor.delivered_index += 1
            cursor.pending[entry.entry_id] = consumer
            cursor.pending_idle_ms[entry.entry_id] = 60_000 if consumer == "consumer-that-died" else 0
            out.append((stream_name.encode(), [(entry.entry_id.encode(), dict(entry.data))]))
        return out

    async def xack(self, stream: str, group: str, entry_id: bytes | str) -> int:
        eid = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
        cursor = self._groups.get(stream, {}).get(group)
        if cursor is None:
            return 0
        removed = cursor.pending.pop(eid, None)
        cursor.pending_idle_ms.pop(eid, None)
        return 1 if removed is not None else 0

    async def xpending_range(
        self,
        stream: str,
        group: str,
        start: str,
        end: str,
        count: int,
    ) -> list[_PendingEntry]:
        del start, end
        cursor = self._groups.get(stream, {}).get(group)
        if cursor is None:
            return []
        rows: list[_PendingEntry] = []
        for entry_id, consumer_name in list(cursor.pending.items())[:count]:
            rows.append(
                _PendingEntry(
                    message_id=entry_id.encode(),
                    consumer=consumer_name.encode(),
                    time_since_delivered=cursor.pending_idle_ms.get(entry_id, 0),
                    times_delivered=1,
                )
            )
        return rows

    async def xautoclaim(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_time: int,
        start_id: str,
        count: int = 50,
    ) -> tuple[bytes, list[tuple[bytes, dict[str, str]]], list[bytes]]:
        del start_id
        cursor = self._groups.get(stream, {}).get(group)
        if cursor is None:
            return (b"0-0", [], [])
        claimed: list[tuple[bytes, dict[str, str]]] = []
        for entry in self._streams.get(stream, []):
            if entry.entry_id not in cursor.pending:
                continue
            if cursor.pending_idle_ms.get(entry.entry_id, 0) < min_idle_time:
                continue
            cursor.pending[entry.entry_id] = consumer
            cursor.pending_idle_ms[entry.entry_id] = 0
            claimed.append((entry.entry_id.encode(), dict(entry.data)))
            if len(claimed) >= count:
                break
        return (b"0-0", claimed, [])

    def consumer_groups(self, stream: str) -> Iterable[str]:
        return tuple(self._groups.get(stream, {}).keys())

    def streams_with_consumer_groups(self) -> Iterable[str]:
        return tuple(self._groups)


async def _drain_bus(bus: EventBus, *, ticks: int = 4) -> None:
    """Run the bus's consumption loop briefly to drain a small fixed batch."""
    shutdown = asyncio.Event()

    async def _stop_after(ticks: int) -> None:
        for _ in range(ticks):
            await asyncio.sleep(0)
        shutdown.set()

    await asyncio.gather(bus.start(shutdown), _stop_after(ticks))


async def _start_and_immediately_shutdown(bus: EventBus) -> None:
    """Run bus startup long enough to register its consumer group."""
    shutdown = asyncio.Event()
    shutdown.set()
    await bus.start(shutdown)


async def test_subscriber_in_different_role_receives_event_emitted_from_another_role() -> None:
    """A subscriber in role X receives events emitted from role Y.

    Catches a regression where the migration delivers internal events only
    within the emitter's role — defeating the cross-process subscription
    goal that motivates the entire migration.
    """
    redis = _RedisStreamFake()
    daemon_bus = EventBus(role="daemon", redis_client=redis)
    runner_bus = EventBus(role="operation-runner", redis_client=redis)

    received: list[str] = []

    async def runner_handler(event: str, context: Any) -> None:
        received.append(getattr(context, "session_id", "?"))

    runner_bus.subscribe("session_started", runner_handler)
    await daemon_bus.emit("session_started", SessionLifecycleContext(session_id="sess-cross"))
    await _drain_bus(runner_bus, ticks=4)

    assert received == ["sess-cross"]


async def test_multiple_instances_of_same_role_share_work() -> None:
    """Within a role, an event is processed by exactly one instance.

    Catches a regression where multiple instances of the same role each
    process every event (duplicate work), or where no instance processes
    the event (lost work). Pins Redis Streams' work-queue semantics
    within a consumer group.
    """
    redis = _RedisStreamFake()
    publisher = EventBus(role="daemon", redis_client=redis)
    consumer_a = EventBus(role="operation-runner", redis_client=redis)
    consumer_b = EventBus(role="operation-runner", redis_client=redis)

    processed_by: list[str] = []

    async def handler_a(event: str, context: Any) -> None:
        processed_by.append(f"A:{getattr(context, 'session_id', '?')}")

    async def handler_b(event: str, context: Any) -> None:
        processed_by.append(f"B:{getattr(context, 'session_id', '?')}")

    consumer_a.subscribe("session_started", handler_a)
    consumer_b.subscribe("session_started", handler_b)

    for n in range(4):
        await publisher.emit("session_started", SessionLifecycleContext(session_id=f"sess-{n}"))

    await asyncio.gather(
        _drain_bus(consumer_a, ticks=8),
        _drain_bus(consumer_b, ticks=8),
    )

    # Each session_id appears exactly once across both instances.
    seen = sorted(token.split(":", 1)[1] for token in processed_by)
    assert seen == ["sess-0", "sess-1", "sess-2", "sess-3"]


async def test_consumer_group_reuses_guaranteed_consumption_contract() -> None:
    """End-to-end: emit publishes an EventEnvelope on a non-cartridge stream and
    the consumer ACKs after successful handler completion.

    Catches a regression where the migration introduces a parallel reliability
    code path (custom XACK loop, pub/sub, in-memory polling) instead of consuming
    the Redis Streams consumer-group + XACK contract delivered by
    guaranteed-event-consumption. Pinned behaviorally: a successful delivery
    drains the PEL via XACK; the wire entry deserializes as an EventEnvelope.
    """
    redis = _RedisStreamFake()
    bus = EventBus(role="daemon", redis_client=redis)
    received: list[str] = []

    async def handler(_event: str, context: Any) -> None:
        received.append(getattr(context, "session_id", "?"))

    bus.subscribe("session_started", handler)
    await bus.emit("session_started", SessionLifecycleContext(session_id="sess-1"))
    await _drain_bus(bus, ticks=4)

    # End-to-end delivery via the consumer-group path.
    assert received == ["sess-1"]

    # Wire format is EventEnvelope, on a stream distinct from the cartridge stream.
    cartridge_stream = "teleclaude:events"
    non_cartridge_streams = [s for s in redis._streams if s != cartridge_stream]
    assert non_cartridge_streams, "emit did not publish to a non-cartridge stream"
    target_stream = non_cartridge_streams[0]
    envelope = EventEnvelope.from_stream_dict(redis._streams[target_stream][-1].data)
    assert envelope.payload.get("session_id") == "sess-1"

    # ACK-after-success drained the PEL; no entries remain pending for any
    # consumer group on the non-cartridge stream.
    pending_counts = [len(cursor.pending) for cursor in redis._groups.get(target_stream, {}).values()]
    assert all(count == 0 for count in pending_counts), "ACK after handler success should drain the PEL"


async def test_stale_pending_entry_is_reclaimed_via_inherited_processor_mechanism() -> None:
    """A pending entry left by a dead consumer is reclaimed and delivered.

    Catches a regression where the migration introduces a custom EventBus
    consumer loop that lacks the cross-consumer stale-reclaim mechanism
    inherited from ``EventProcessor``. If the bus reuses the EventProcessor
    code path (as the requirements demand), a stale entry from a different
    consumer name within the same role's consumer group is reclaimed and
    redelivered. A custom loop without the inherited mechanism would leave
    the entry stuck in the PEL.
    """
    redis = _RedisStreamFake()
    publisher = EventBus(role="daemon", redis_client=redis)
    bootstrap_consumer = EventBus(role="operation-runner", redis_client=redis)
    await _start_and_immediately_shutdown(bootstrap_consumer)

    streams = tuple(redis.streams_with_consumer_groups())
    assert streams
    target_stream = streams[0]
    groups = tuple(redis.consumer_groups(target_stream))
    assert groups
    target_group = groups[0]

    await publisher.emit("session_started", SessionLifecycleContext(session_id="sess-stale-1"))
    staged = await redis.xreadgroup(
        target_group,
        "consumer-that-died",
        {target_stream: ">"},
        count=1,
    )
    assert staged

    received: list[str] = []

    async def handler(_event: str, context: Any) -> None:
        received.append(getattr(context, "session_id", "?"))

    consumer = EventBus(role="operation-runner", redis_client=redis)
    consumer.subscribe("session_started", handler)
    await _drain_bus(consumer, ticks=8)

    # The stale entry must have been reclaimed and the handler invoked.
    assert "sess-stale-1" in received, (
        "stale-reclaim must redeliver entries left by a dead consumer; "
        "a custom EventBus consumer loop without the inherited reclaim "
        "mechanism would not satisfy this"
    )


async def test_transcript_format_mismatch_emits_typed_error_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _RedisStreamFake()
    bus = EventBus(role="daemon", redis_client=redis)
    received: list[Any] = []

    async def handler(_event: str, context: Any) -> None:
        received.append(context)

    bus.subscribe(TeleClaudeEvents.ERROR, handler)
    monkeypatch.setattr(transcript_iterators, "event_bus", bus)
    transcript_iterators._REPORTED_TRANSCRIPT_FORMAT_MISMATCHES.clear()

    transcript_path = tmp_path / "gemini-session.jsonl"
    transcript_path.write_text("{malformed json\n", encoding="utf-8")

    entries = transcript_iterators._get_entries_for_agent(str(transcript_path), AgentName.GEMINI)
    await _drain_bus(bus, ticks=4)

    assert entries == []
    assert len(received) == 1
    context = received[0]
    assert isinstance(context, ErrorEventContext)
    assert context.session_id is None
    assert context.severity == "warning"
    assert context.message


async def test_title_background_task_failure_emits_typed_error_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _RedisStreamFake()
    bus = EventBus(role="daemon", redis_client=redis)
    received: list[Any] = []

    async def handler(_event: str, context: Any) -> None:
        received.append(context)

    async def failing_title_update() -> None:
        raise RuntimeError("title unavailable")

    bus.subscribe(TeleClaudeEvents.ERROR, handler)
    monkeypatch.setattr(coordinator_module, "event_bus", bus)

    coordinator = AgentCoordinator(
        client=cast(Any, object()),
        tts_manager=cast(Any, object()),
    )
    coordinator._queue_background_task(failing_title_update(), "update-title")
    for _ in range(4):
        await asyncio.sleep(0)
    await _drain_bus(bus, ticks=4)

    assert len(received) == 1
    context = received[0]
    assert isinstance(context, ErrorEventContext)
    assert context.session_id is None
    assert context.severity == "warning"
    assert context.message


async def test_event_bus_rejects_dict_context_and_round_trips_error_context() -> None:
    redis = _RedisStreamFake()
    publisher = EventBus(role="daemon", redis_client=redis)
    consumer = EventBus(role="operation-runner", redis_client=redis)

    with pytest.raises(TypeError):
        await publisher.emit(TeleClaudeEvents.ERROR, cast(Any, {"message": "x"}))

    received: list[Any] = []

    async def handler(_event: str, context: Any) -> None:
        received.append(context)

    consumer.subscribe(TeleClaudeEvents.ERROR, handler)
    await publisher.emit(
        TeleClaudeEvents.ERROR,
        ErrorEventContext(session_id=None, message="x", source="s", severity="warning"),
    )
    await _drain_bus(consumer, ticks=4)

    assert len(received) == 1
    context = received[0]
    assert isinstance(context, ErrorEventContext)
    assert context.session_id is None
    assert context.source
    assert context.severity == "warning"
