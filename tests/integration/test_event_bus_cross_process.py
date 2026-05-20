"""Integration specs for ``event-bus-redis-migration`` cross-process delivery.

These specs pin the cross-process, inter-role, and inherited-reliability
behaviors of the Redis-Streams-backed ``EventBus`` adapter.

Most specs run against a Redis fake that preserves consumer-group cursor and
PEL semantics, simulating cross-process delivery without spawning processes.
``test_subscriber_in_separate_subprocess_receives_event_emitted_from_parent_process``
exercises a real OS process boundary using ``multiprocessing``.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, TypedDict

import pytest

from teleclaude.core.event_bus import INTERNAL_EVENT_STREAM, EventBus
from teleclaude.core.events import SessionLifecycleContext
from teleclaude.events.envelope import EventEnvelope
from teleclaude.transport.redis_client import create_redis_client


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


async def _require_live_redis(redis_url: str) -> None:
    """Skip live-Redis subprocess smoke when Redis is unavailable locally."""
    redis = create_redis_client(
        redis_url,
        password=os.environ.get("REDIS_PASSWORD"),
        max_connections=2,
        socket_timeout=0.2,
    )
    try:
        await redis.ping()
    except Exception as exc:
        pytest.skip(f"live Redis unavailable for subprocess EventBus smoke: {exc}")
    finally:
        await redis.aclose()


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


def _subprocess_subscriber(redis_url: str, role: str, output_path: str, ready_event_name: str) -> None:
    """Subscriber worker run in a separate Python process.

    Connects to the live Redis instance addressed by ``redis_url``, registers
    a subscriber on the bus, signals readiness via the file at ``output_path``,
    and writes the received session_id to ``output_path`` when the handler
    fires. The entrypoint uses the shared Redis client factory directly so
    the spec cannot pass through shared in-memory state.
    """
    redis = create_redis_client(
        redis_url,
        password=os.environ.get("REDIS_PASSWORD"),
        max_connections=10,
        socket_timeout=1.0,
    )
    bus = EventBus(role=role, redis_client=redis)
    received: list[str] = []

    async def handler(_event: str, context: Any) -> None:
        sid = getattr(context, "session_id", "?")
        received.append(sid)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(sid)

    bus.subscribe("session_started", handler)

    async def _run() -> None:
        try:
            await redis.xgroup_create(INTERNAL_EVENT_STREAM, f"event-bus:{role}", id="$", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        # Signal readiness so the parent knows the consumer group exists.
        with open(ready_event_name, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))

        shutdown = asyncio.Event()

        # Run for a bounded amount of time, then exit so the test does not hang.
        async def _stop_after(timeout: float) -> None:
            await asyncio.sleep(timeout)
            shutdown.set()

        await asyncio.gather(bus.start(shutdown), _stop_after(5.0))

    asyncio.run(_run())


@pytest.mark.expensive
async def test_subscriber_in_separate_subprocess_receives_event_emitted_from_parent_process(
    tmp_path: Any,
) -> None:
    """A subscriber in a separate Python subprocess receives an event emitted
    from the parent process via the Redis-Streams-backed bus.

    Catches a regression where the migration's cross-process semantics rely
    on shared in-memory state instead of Redis-side delivery — which would
    break the subprocess subscription that motivates the entire migration.

    The test requires a live Redis instance addressable at ``REDIS_URL`` (or
    the project default). Without Redis, the test skips before spawning the
    subprocess because the fake-Redis integration specs cover deterministic
    cross-role and work-sharing behavior.
    """
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    await _require_live_redis(redis_url)
    output_path = str(tmp_path / "subscriber.out")
    ready_path = str(tmp_path / "subscriber.ready")
    subscriber_role = f"operation-runner-{os.getpid()}-{tmp_path.name}"

    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(
        target=_subprocess_subscriber,
        args=(redis_url, subscriber_role, output_path, ready_path),
    )
    proc.start()
    try:
        # Wait briefly for subscriber readiness.
        for _ in range(40):
            if os.path.exists(ready_path):
                break
            await asyncio.sleep(0.05)
        assert os.path.exists(ready_path), "subprocess subscriber never signaled readiness"

        redis = create_redis_client(
            redis_url,
            password=os.environ.get("REDIS_PASSWORD"),
            max_connections=10,
            socket_timeout=1.0,
        )
        publisher = EventBus(role="daemon", redis_client=redis)
        await publisher.emit("session_started", SessionLifecycleContext(session_id="sess-subproc"))

        # Wait for the subprocess to record the received session_id.
        for _ in range(40):
            if os.path.exists(output_path):
                break
            await asyncio.sleep(0.05)
        assert os.path.exists(output_path), "subprocess subscriber never received the event"
        assert open(output_path, encoding="utf-8").read() == "sess-subproc"
    finally:
        proc.terminate()
        proc.join(timeout=2)


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
