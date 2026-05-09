"""Characterization tests for teleclaude.events.processor."""

from __future__ import annotations

import asyncio
import logging
import os
import time as _time_mod
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.config import config as _config
from teleclaude.events import producer as _producer_module
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.events.pipeline import Pipeline, PipelineContext
from teleclaude.events.processor import (
    CONSUMER_GROUP,
    STREAM_NAME,
    EventProcessor,
)


def _make_envelope() -> EventEnvelope:
    return EventEnvelope(event="test.event", source="test", level=EventLevel.OPERATIONAL)


def _make_redis() -> MagicMock:
    redis = MagicMock()
    redis.xgroup_create = AsyncMock()
    redis.xreadgroup = AsyncMock(return_value=[])
    redis.xack = AsyncMock()
    return redis


class TestConstants:
    def test_stream_name(self) -> None:
        assert STREAM_NAME == "teleclaude:events"

    def test_consumer_group(self) -> None:
        assert CONSUMER_GROUP == "event-processor"


class TestEventProcessorInit:
    def test_default_stream(self) -> None:
        redis = _make_redis()
        pipeline = MagicMock()
        processor = EventProcessor(redis, pipeline)
        assert processor._stream == STREAM_NAME

    def test_default_group(self) -> None:
        redis = _make_redis()
        pipeline = MagicMock()
        processor = EventProcessor(redis, pipeline)
        assert processor._group == CONSUMER_GROUP

    def test_custom_stream_and_group(self) -> None:
        redis = _make_redis()
        pipeline = MagicMock()
        processor = EventProcessor(redis, pipeline, stream="s", group="g")
        assert processor._stream == "s"
        assert processor._group == "g"

    def test_consumer_name_override(self) -> None:
        redis = _make_redis()
        pipeline = MagicMock()
        processor = EventProcessor(redis, pipeline, consumer_name="my-consumer")
        assert processor._consumer == "my-consumer"

    def test_consumer_name_defaults_to_pid_based(self) -> None:
        redis = _make_redis()
        pipeline = MagicMock()
        processor = EventProcessor(redis, pipeline)
        assert f"{os.getpid()}" in processor._consumer

    def test_reliability_kwargs_override_config_defaults(self) -> None:
        redis = _make_redis()
        pipeline = MagicMock()
        processor = EventProcessor(
            redis,
            pipeline,
            idle_threshold_ms=12_000,
            max_attempts=8,
            sweep_interval_ms=700,
            dlq_destination="custom:dlq",
        )

        assert processor._idle_threshold_ms == 12_000
        assert processor._max_attempts == 8
        assert processor._sweep_interval_ms == 700
        assert processor._dlq_destination == "custom:dlq"

    def test_reliability_defaults_come_from_config_surface(self) -> None:
        redis = _make_redis()
        pipeline = MagicMock()
        processor = EventProcessor(redis, pipeline)

        assert processor._idle_threshold_ms == _config.event_reliability.idle_threshold_ms
        assert processor._max_attempts == _config.event_reliability.max_attempts
        assert processor._sweep_interval_ms == _config.event_reliability.sweep_interval_ms
        assert processor._dlq_destination == _config.event_reliability.dlq_destination


class TestEventProcessorStart:
    @pytest.mark.asyncio
    async def test_start_creates_consumer_group(self) -> None:
        redis = _make_redis()
        redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock()
        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()
        await processor.start(shutdown)
        redis.xgroup_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_handles_busygroup_error(self) -> None:
        redis = _make_redis()
        redis.xgroup_create = AsyncMock(side_effect=Exception("BUSYGROUP already exists"))
        redis.xreadgroup = AsyncMock(return_value=[])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock()
        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()
        # Should not raise on BUSYGROUP
        await processor.start(shutdown)

    @pytest.mark.asyncio
    async def test_start_raises_on_non_busygroup_xgroup_error(self) -> None:
        redis = _make_redis()
        redis.xgroup_create = AsyncMock(side_effect=Exception("connection refused"))
        pipeline = MagicMock()
        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()
        with pytest.raises(Exception, match="connection refused"):
            await processor.start(shutdown)


class TestProcessEntries:
    @pytest.mark.asyncio
    async def test_processes_entries_and_acks(self) -> None:
        event = _make_envelope()
        stream_dict = event.to_stream_dict()
        entries = [("stream", [("entry-1", stream_dict)])]

        redis = _make_redis()
        redis.xreadgroup = AsyncMock(side_effect=[entries, asyncio.CancelledError()])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(return_value=event)
        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()
        await processor.start(shutdown)
        pipeline.execute.assert_called_once()
        redis.xack.assert_called_once()

    @pytest.mark.asyncio
    async def test_acks_even_if_pipeline_returns_none(self) -> None:
        event = _make_envelope()
        stream_dict = event.to_stream_dict()
        entries = [("stream", [("entry-1", stream_dict)])]

        redis = _make_redis()
        redis.xreadgroup = AsyncMock(side_effect=[entries, asyncio.CancelledError()])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(return_value=None)
        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()
        await processor.start(shutdown)
        redis.xack.assert_called_once()


# ---------------------------------------------------------------------------
# Specs (xfail) for guaranteed-event-consumption
#
# These specs assert ONLY behaviors the requirement criteria literally name.
# Implementation choices — Redis primitives, config namespaces, DLQ
# destinations, attempt-count storage, metrics interfaces — are deliberately
# NOT pinned here. Remove ``pytestmark = pytest.mark.xfail`` once the
# implementation satisfies the contract.
# ---------------------------------------------------------------------------


def _make_redis_with_reclaim() -> MagicMock:
    """Redis mock extended with reclaim-related primitives.

    Each method returns an empty default; tests override only what the
    individual scenario stages. The implementation may choose any subset of
    primitives; the helper is just a permissive surface.
    """
    redis = MagicMock()
    redis.xgroup_create = AsyncMock()
    redis.xreadgroup = AsyncMock(return_value=[])
    redis.xack = AsyncMock()
    redis.xpending = AsyncMock(return_value=[])
    redis.xpending_range = AsyncMock(return_value=[])
    redis.xclaim = AsyncMock(return_value=[])
    redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))
    redis.xadd = AsyncMock(return_value=b"dlq-1")
    return redis


@contextmanager
def _configured_event_producer() -> Iterator[MagicMock]:
    producer_mock = MagicMock()
    producer_mock.emit = AsyncMock(return_value="0-0")
    original_producer = _producer_module._PRODUCER_STATE.get("producer")
    _producer_module._PRODUCER_STATE["producer"] = producer_mock
    try:
        yield producer_mock
    finally:
        _producer_module._PRODUCER_STATE["producer"] = original_producer


def _make_processor_with_reliability_overrides(
    redis: object,
    pipeline: object,
    *,
    idle_threshold_ms: int | None = None,
    max_attempts: int | None = None,
    sweep_interval_ms: int | None = None,
    dlq_destination: str | None = None,
) -> EventProcessor:
    """Test helper that builds an ``EventProcessor`` configured with the
    given reliability overrides.

    The implementation may satisfy these overrides through the established
    project configuration surface, constructor options, or any other public
    configuration seam — the spec body does NOT prescribe which. During the
    build phase, wire this helper to whichever public seam the implementation
    chooses.

    The build phase wires this helper to the constructor seam used by the
    daemon so specs can exercise configuration-sensitive reliability behavior.
    """
    return EventProcessor(
        redis,
        pipeline,
        idle_threshold_ms=idle_threshold_ms,
        max_attempts=max_attempts,
        sweep_interval_ms=sweep_interval_ms,
        dlq_destination=dlq_destination,
    )


class TestEventProcessorStaleReclaimSpecs:
    """Pending entries owned by other consumers must be reclaimed and re-delivered.

    Verbatim requirement criterion (from `requirements.md`):

    > **Stale pending recovery.** Pending entries whose owning consumer has
    > not progressed within a configurable idle threshold are reclaimed and
    > re-delivered, both on daemon startup and periodically while the daemon
    > runs. Reclaim is not limited to entries owned by the current consumer
    > name.
    """

    @pytest.mark.asyncio
    async def test_pipeline_executes_for_entry_owned_by_another_consumer(self) -> None:
        """Reclaim is not limited to current-consumer entries — a stale
        pending entry owned by a non-current consumer is redelivered.
        """
        event = _make_envelope()
        stream_dict = event.to_stream_dict()
        other_owner_entry = [("entry-from-other-consumer", stream_dict)]

        redis = _make_redis_with_reclaim()
        redis.xautoclaim = AsyncMock(return_value=("0-0", other_owner_entry, []))
        redis.xclaim = AsyncMock(return_value=other_owner_entry)
        redis.xpending_range = AsyncMock(
            return_value=[
                {
                    "message_id": b"entry-from-other-consumer",
                    "consumer": b"other-consumer",
                    "time_since_delivered": 60_000,
                    "times_delivered": 1,
                }
            ]
        )
        redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])

        pipeline = MagicMock()
        pipeline.execute = AsyncMock(return_value=event)
        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()

        with _configured_event_producer():
            await processor.start(shutdown)

        assert pipeline.execute.await_count >= 1

    @pytest.mark.asyncio
    async def test_idle_threshold_is_configurable(self) -> None:
        """The criterion says "configurable idle threshold." The same pending
        entry, with the same fake-Redis behavior, must be reclaimed under one
        operator-configured idle threshold and NOT reclaimed under a higher
        one — proving the threshold is actually a configurable knob, not a
        hard-coded constant.
        """
        env = EventEnvelope(event="test.threshold", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = env.to_stream_dict()
        entry_idle_ms = 30_000

        async def _filter(min_idle_time: int) -> list[tuple[str, object]]:
            if entry_idle_ms >= min_idle_time:
                return [("entry-under-test", stream_dict)]
            return []

        def _build_redis() -> MagicMock:
            r = _make_redis_with_reclaim()

            async def fake_xautoclaim(*args: object, **_k: object) -> object:
                # Real XAUTOCLAIM: name, group, consumer, min_idle_time, ...
                min_idle = int(args[3]) if len(args) >= 4 else 0
                return ("0-0", await _filter(min_idle), [])

            async def fake_xclaim(*args: object, **_k: object) -> object:
                min_idle = int(args[3]) if len(args) >= 4 else 0
                return await _filter(min_idle)

            r.xautoclaim = AsyncMock(side_effect=fake_xautoclaim)
            r.xclaim = AsyncMock(side_effect=fake_xclaim)
            r.xpending_range = AsyncMock(
                return_value=[
                    {
                        "message_id": b"entry-under-test",
                        "consumer": b"other-consumer",
                        "time_since_delivered": entry_idle_ms,
                        "times_delivered": 1,
                    }
                ]
            )
            r.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
            return r

        # Scenario A: low threshold — entry is stale relative to it, must be reclaimed.
        redis_low = _build_redis()
        pipeline_low = MagicMock()
        pipeline_low.execute = AsyncMock(return_value=env)
        processor_low = _make_processor_with_reliability_overrides(redis_low, pipeline_low, idle_threshold_ms=10_000)
        shutdown_low = asyncio.Event()
        shutdown_low.set()
        await processor_low.start(shutdown_low)
        low_processed = pipeline_low.execute.await_count

        # Scenario B: high threshold — entry is fresh relative to it, must NOT be reclaimed.
        redis_high = _build_redis()
        pipeline_high = MagicMock()
        pipeline_high.execute = AsyncMock(return_value=env)
        processor_high = _make_processor_with_reliability_overrides(
            redis_high, pipeline_high, idle_threshold_ms=120_000
        )
        shutdown_high = asyncio.Event()
        shutdown_high.set()
        await processor_high.start(shutdown_high)
        high_processed = pipeline_high.execute.await_count

        assert low_processed >= 1, (
            f"under low idle threshold, the stale entry must be reclaimed; got {low_processed} pipeline runs"
        )
        assert high_processed == 0, (
            "under high idle threshold, the entry is below threshold and must NOT "
            f"be reclaimed; got {high_processed} pipeline runs"
        )

    @pytest.mark.asyncio
    async def test_entry_becoming_stale_mid_run_is_reclaimed_on_later_sweep(self) -> None:
        """The criterion says reclaim happens "periodically while the daemon
        runs." An entry that becomes eligible AFTER the first sweep must be
        reclaimed by a later sweep, without daemon restart.
        """
        late_env = EventEnvelope(event="test.late", source="t", level=EventLevel.OPERATIONAL)
        late_stream_dict = late_env.to_stream_dict()
        sweep_count = {"n": 0}
        shutdown = asyncio.Event()

        async def autoclaim_with_late_arrival(*_args: object, **_kwargs: object) -> object:
            sweep_count["n"] += 1
            if sweep_count["n"] == 1:
                return ("0-0", [], [])
            shutdown.set()
            return ("0-0", [("entry-late", late_stream_dict)], [])

        async def xclaim_with_late_arrival(*_args: object, **_kwargs: object) -> list[tuple[str, object]]:
            sweep_count["n"] += 1
            if sweep_count["n"] == 1:
                return []
            shutdown.set()
            return [("entry-late", late_stream_dict)]

        redis = _make_redis_with_reclaim()
        redis.xautoclaim = AsyncMock(side_effect=autoclaim_with_late_arrival)
        redis.xclaim = AsyncMock(side_effect=xclaim_with_late_arrival)
        redis.xreadgroup = AsyncMock(return_value=[])

        pipeline = MagicMock()
        pipeline.execute = AsyncMock(return_value=late_env)
        processor = EventProcessor(redis, pipeline, sweep_interval_ms=1)

        await processor.start(shutdown)

        processed_event_fields = [call.args[0].event for call in pipeline.execute.await_args_list]
        assert "test.late" in processed_event_fields, (
            "an entry becoming stale during an active daemon run must be "
            f"reclaimed by a later sweep; pipeline saw {processed_event_fields!r}"
        )


def _collect_dlq_outputs(redis: MagicMock, input_stream: str) -> list[object]:
    """Collect every value that any plausible DLQ persistence mechanism saw.

    The implementation may persist to a non-input Redis stream, a separate
    store, a database, etc. This helper observes the ones the test rig can
    see — Redis xadd to a non-input stream — and returns the staged values.
    """
    haystack: list[object] = []
    for call in redis.xadd.await_args_list:
        if call.args and call.args[0] != input_stream:
            haystack.append(call.args[0])
            for arg in call.args[1:]:
                haystack.append(arg)
            for value in call.kwargs.values():
                haystack.append(value)
    return haystack


def _flatten_to_string(values: list[object]) -> str:
    """Flatten a list of arbitrary values to a searchable string haystack."""
    parts: list[str] = []

    def _walk(v: object) -> None:
        if isinstance(v, dict):
            for k, vv in v.items():
                parts.append(str(k))
                _walk(vv)
        elif isinstance(v, list | tuple | set):
            for item in v:
                _walk(item)
        else:
            parts.append(str(v))

    _walk(values)
    return " ".join(parts)


class TestEventProcessorRetryAndDlqSpecs:
    """After repeated failure, the event transitions to a dead-letter outcome
    that carries the diagnostic items the criterion names.

    Verbatim requirement criterion (from `requirements.md`):

    > **Retry ceiling and dead-letter.** When the cumulative attempt count
    > for a pending entry exceeds a configurable threshold, the event
    > transitions to a dead-letter destination carrying replay/triage-
    > sufficient diagnostics: the original event envelope, the original
    > stream and entry identity, the cumulative attempt count, a failure
    > classification or message, the failing stage where known, first and
    > last attempt timestamps where known, and the daemon/consumer identity
    > where known. The attempt count is consistent across normal failures,
    > reclaimed stale deliveries, and daemon restarts.
    """

    @pytest.mark.asyncio
    async def test_retry_exhaustion_transitions_to_dead_letter_with_named_diagnostics(
        self,
    ) -> None:
        """The dead-letter outcome must carry the criterion-named items as
        observable values: original envelope content, original stream id,
        original entry id, cumulative attempt count, failure classification,
        and daemon/consumer identity. Stage and timestamps are "where
        known" — not asserted.
        """
        original_stream = STREAM_NAME
        original_entry_id = "entry-poison-12345"
        prior_consumer = "prior-consumer-9"
        prior_attempts = 7
        failure_marker = "permanent-failure-marker-XYZ"
        envelope_event = "test.poison.v1"

        envelope = EventEnvelope(event=envelope_event, source="poison-source", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()

        redis = _make_redis_with_reclaim()
        redis.xautoclaim = AsyncMock(return_value=("0-0", [(original_entry_id, stream_dict)], []))
        redis.xpending_range = AsyncMock(
            return_value=[
                {
                    "message_id": original_entry_id.encode(),
                    "consumer": prior_consumer.encode(),
                    "time_since_delivered": 60_000,
                    "times_delivered": prior_attempts,
                }
            ]
        )
        redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(side_effect=RuntimeError(failure_marker))

        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()

        with _configured_event_producer():
            await processor.start(shutdown)

        haystack_values = _collect_dlq_outputs(redis, processor._stream)
        assert haystack_values, (
            "after retry exhaustion, the event must transition to a dead-letter "
            "destination distinct from the input stream"
        )
        haystack = _flatten_to_string(haystack_values)

        # Each criterion-named diagnostic concept must be observable in the
        # DLQ output, by VALUE (the test stages a known value for each).
        for name, expected in (
            ("original event envelope", envelope_event),
            ("original stream identity", original_stream),
            ("original entry identity", original_entry_id),
            ("failure classification or message", failure_marker),
            ("daemon/consumer identity", prior_consumer),
        ):
            assert expected in haystack, (
                f"DLQ outcome must carry {name!r} (expected {expected!r} in output); haystack was {haystack!r}"
            )

        # Cumulative attempt count: SOME numeric value in the haystack must
        # be at least the prior delivery count — i.e. the count is preserved
        # across the transition, not reset.
        ints: list[int] = []
        for v in haystack_values:
            if isinstance(v, dict):
                for vv in v.values():
                    try:
                        ints.append(int(vv))
                    except (TypeError, ValueError):
                        continue
            else:
                try:
                    ints.append(int(v))
                except (TypeError, ValueError):
                    continue
        assert any(c >= prior_attempts for c in ints), (
            f"DLQ outcome must carry cumulative attempt count >= {prior_attempts}; observed numeric values {ints!r}"
        )

    @pytest.mark.asyncio
    async def test_attempt_count_preserved_across_normal_redelivery(self) -> None:
        """Repeated failure via the normal read path produces a DLQ outcome
        whose attempt count reflects the cumulative count, not a reset.
        """
        envelope = EventEnvelope(event="test.replay", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()
        entries = [("stream", [("entry-replay", stream_dict)])]

        redis = _make_redis_with_reclaim()
        redis.xreadgroup = AsyncMock(side_effect=[entries, entries, entries, asyncio.CancelledError()])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(side_effect=RuntimeError("repeated failure"))

        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()

        with _configured_event_producer():
            await processor.start(shutdown)

        haystack_values = _collect_dlq_outputs(redis, processor._stream)
        assert haystack_values, "expected a DLQ outcome after repeated failures"
        ints: list[int] = []
        for v in haystack_values:
            if isinstance(v, dict):
                for vv in v.values():
                    try:
                        ints.append(int(vv))
                    except (TypeError, ValueError):
                        continue
        assert any(c >= 2 for c in ints), (
            "DLQ outcome must carry cumulative attempt count >= 2 across normal redeliveries"
        )

    @pytest.mark.asyncio
    async def test_attempt_count_preserved_across_stale_reclaim(self) -> None:
        """A reclaimed stale entry's DLQ outcome carries an attempt count
        reflecting prior deliveries, not reset on reclaim.
        """
        envelope = EventEnvelope(event="test.reclaim", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()
        prior = 5

        redis = _make_redis_with_reclaim()
        redis.xautoclaim = AsyncMock(return_value=("0-0", [("entry-reclaimed", stream_dict)], []))
        redis.xpending_range = AsyncMock(
            return_value=[
                {
                    "message_id": b"entry-reclaimed",
                    "consumer": b"prior-consumer",
                    "time_since_delivered": 10_000,
                    "times_delivered": prior,
                }
            ]
        )
        redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(side_effect=RuntimeError("reclaim failure"))

        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()

        await processor.start(shutdown)

        haystack_values = _collect_dlq_outputs(redis, processor._stream)
        assert haystack_values, "expected a DLQ outcome after reclaim+failure"
        ints: list[int] = []
        for v in haystack_values:
            if isinstance(v, dict):
                for vv in v.values():
                    try:
                        ints.append(int(vv))
                    except (TypeError, ValueError):
                        continue
        assert any(c >= prior for c in ints), (
            f"reclaimed entry's DLQ outcome must carry cumulative attempt count >= {prior}"
        )

    @pytest.mark.asyncio
    async def test_attempt_count_preserved_across_daemon_restart(self) -> None:
        """A pending entry recovered after daemon restart preserves its
        prior attempt count when it eventually transitions to DLQ.
        """
        envelope = EventEnvelope(event="test.restart", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()
        prior = 3

        redis = _make_redis_with_reclaim()
        redis.xpending_range = AsyncMock(
            return_value=[
                {
                    "message_id": b"entry-recovered",
                    "consumer": b"prior-pid-consumer",
                    "time_since_delivered": 5_000,
                    "times_delivered": prior,
                }
            ]
        )
        redis.xautoclaim = AsyncMock(return_value=("0-0", [("entry-recovered", stream_dict)], []))
        redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(side_effect=RuntimeError("post-restart failure"))

        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()

        await processor.start(shutdown)

        haystack_values = _collect_dlq_outputs(redis, processor._stream)
        assert haystack_values, "expected a DLQ outcome after restart-recovery+failure"
        ints: list[int] = []
        for v in haystack_values:
            if isinstance(v, dict):
                for vv in v.values():
                    try:
                        ints.append(int(vv))
                    except (TypeError, ValueError):
                        continue
        assert any(c >= prior for c in ints), f"post-restart DLQ outcome must carry cumulative attempt count >= {prior}"

    @pytest.mark.asyncio
    async def test_below_retry_ceiling_failure_does_not_acknowledge_or_dead_letter(
        self,
    ) -> None:
        """A required-processing failure that has NOT exhausted the retry
        ceiling must not be acknowledged, must not produce a dead-letter
        outcome, and must remain eligible for a later retry. Configured
        with a high retry threshold via the test helper, a single failure
        is below the ceiling.
        """
        envelope = EventEnvelope(event="test.below.ceiling", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()
        original_entry_id = "entry-below-ceiling"

        redis = _make_redis_with_reclaim()
        redis.xautoclaim = AsyncMock(return_value=("0-0", [(original_entry_id, stream_dict)], []))
        redis.xpending_range = AsyncMock(
            return_value=[
                {
                    "message_id": original_entry_id.encode(),
                    "consumer": b"prior-consumer",
                    "time_since_delivered": 60_000,
                    "times_delivered": 1,
                }
            ]
        )
        redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(side_effect=RuntimeError("transient failure"))

        # High threshold: a single failure is well below the ceiling.
        processor = _make_processor_with_reliability_overrides(redis, pipeline, max_attempts=10)
        shutdown = asyncio.Event()
        shutdown.set()

        await processor.start(shutdown)

        # 1) Pipeline was attempted.
        assert pipeline.execute.await_count >= 1, (
            "below-ceiling failure must still attempt the pipeline; got 0 attempts"
        )
        # 2) Not acknowledged — entry remains in pending.
        redis.xack.assert_not_called()
        # 3) No dead-letter outcome — below ceiling.
        dlq_outputs = _collect_dlq_outputs(redis, processor._stream)
        assert not dlq_outputs, (
            f"below-ceiling failure must NOT transition to dead-letter; saw DLQ outputs: {dlq_outputs!r}"
        )

    @pytest.mark.asyncio
    async def test_retry_ceiling_is_configurable(self) -> None:
        """The same failure scenario, run under two operator-configured
        retry thresholds, must produce different DLQ outcomes — proving
        the ceiling is actually configurable, not a hard-coded constant.
        """
        envelope = EventEnvelope(event="test.threshold.dlq", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()
        prior_attempts = 3

        def _build_redis() -> MagicMock:
            r = _make_redis_with_reclaim()
            r.xautoclaim = AsyncMock(return_value=("0-0", [("entry-config-test", stream_dict)], []))
            r.xpending_range = AsyncMock(
                return_value=[
                    {
                        "message_id": b"entry-config-test",
                        "consumer": b"prior-consumer",
                        "time_since_delivered": 60_000,
                        "times_delivered": prior_attempts,
                    }
                ]
            )
            r.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
            return r

        # Scenario A: ceiling = 1 (already exceeded by 3 prior attempts) → DLQ.
        redis_low = _build_redis()
        pipeline_low = MagicMock()
        pipeline_low.execute = AsyncMock(side_effect=RuntimeError("fail"))
        processor_low = _make_processor_with_reliability_overrides(redis_low, pipeline_low, max_attempts=1)
        shutdown_low = asyncio.Event()
        shutdown_low.set()
        await processor_low.start(shutdown_low)
        dlq_low = _collect_dlq_outputs(redis_low, processor_low._stream)

        # Scenario B: ceiling = 100 (well above 3 prior attempts) → no DLQ.
        redis_high = _build_redis()
        pipeline_high = MagicMock()
        pipeline_high.execute = AsyncMock(side_effect=RuntimeError("fail"))
        processor_high = _make_processor_with_reliability_overrides(redis_high, pipeline_high, max_attempts=100)
        shutdown_high = asyncio.Event()
        shutdown_high.set()
        await processor_high.start(shutdown_high)
        dlq_high = _collect_dlq_outputs(redis_high, processor_high._stream)

        assert dlq_low, "under low retry ceiling (1), exceeded entry must transition to DLQ"
        assert not dlq_high, (
            f"under high retry ceiling (100), 3 prior attempts is below ceiling; DLQ must not fire. saw {dlq_high!r}"
        )

    @pytest.mark.asyncio
    async def test_dlq_outcome_includes_known_failing_stage_and_attempt_timestamps(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When the failing stage and attempt timestamps are knowable to the
        implementation, they must appear in the DLQ outcome.

        - Stage marker: failing cartridge ``name`` attribute (real Pipeline).
        - Timestamps: monkeypatched clock that returns two distinct,
          recognizable epoch values. The implementation's first time-of-
          attempt observation gets ``FIRST_AT_MARKER``; subsequent ones get
          ``LAST_AT_MARKER``. If the implementation records first/last
          attempt timestamps, BOTH markers appear in the DLQ outcome.
        """
        stage_marker = "TEST-STAGE-MARKER-RT-9KQ"
        first_at_marker = 1_700_000_111
        last_at_marker = 1_700_000_999
        envelope = EventEnvelope(event="test.poison.stage", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()

        # Sequence of clock readings: first reading = first-attempt marker,
        # subsequent readings = last-attempt marker. Implementations that
        # capture timestamps via time.time() (or time.monotonic_ns) record
        # both markers across the attempt lifecycle.
        clock_calls = {"n": 0}

        def fake_time() -> float:
            clock_calls["n"] += 1
            if clock_calls["n"] == 1:
                return float(first_at_marker)
            return float(last_at_marker)

        monkeypatch.setattr(_time_mod, "time", fake_time)

        # Real Pipeline with a single failing cartridge whose `name` is the
        # stage marker. If the implementation captures the failing
        # cartridge's name as "stage", the marker will appear in the DLQ.
        failing_cartridge = MagicMock()
        failing_cartridge.name = stage_marker
        failing_cartridge.process = AsyncMock(side_effect=RuntimeError("stage-fail"))
        pipeline = Pipeline(
            [failing_cartridge],
            PipelineContext(catalog=MagicMock(), db=MagicMock()),
        )

        redis = _make_redis_with_reclaim()
        redis.xautoclaim = AsyncMock(return_value=("0-0", [("entry-stage-marker", stream_dict)], []))
        redis.xpending_range = AsyncMock(
            return_value=[
                {
                    "message_id": b"entry-stage-marker",
                    "consumer": b"prior-consumer",
                    "time_since_delivered": 60_000,
                    "times_delivered": 99,
                }
            ]
        )
        redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])

        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()

        await processor.start(shutdown)

        haystack_values = _collect_dlq_outputs(redis, processor._stream)
        assert haystack_values, "expected DLQ outcome after retry exhaustion"
        haystack = _flatten_to_string(haystack_values)

        assert stage_marker in haystack, (
            f"DLQ outcome must carry the failing-stage marker {stage_marker!r}; haystack was {haystack!r}"
        )
        # Both first-attempt and last-attempt timestamp markers must appear,
        # not just one. Echoing the Redis idle duration alone (e.g.
        # time_since_delivered) does not satisfy the criterion.
        assert str(first_at_marker) in haystack, (
            f"DLQ outcome must carry the first-attempt timestamp marker {first_at_marker!r}; haystack was {haystack!r}"
        )
        assert str(last_at_marker) in haystack, (
            f"DLQ outcome must carry the last-attempt timestamp marker {last_at_marker!r}; haystack was {haystack!r}"
        )


class TestEventProcessorAtomicitySpecs:
    """Acknowledgment waits for the dead-letter record AND the observable
    signal; duplicate dead-letter records after a failed ack are tolerated
    by original entry identity.

    Verbatim requirement criterion (from `requirements.md`):

    > **Dead-letter atomicity.** A pending entry exhausting its retry ceiling
    > is not acknowledged or removed from the pending entry list until the
    > dead-letter record and its observable signal have been written, or are
    > durably recoverable. Duplicate dead-letter records caused by re-delivery
    > after a failed acknowledgment are tolerated by original entry identity.
    """

    @pytest.mark.asyncio
    async def test_does_not_acknowledge_when_dead_letter_persistence_fails(self) -> None:
        """If the DLQ persistence pathway fails, the entry must NOT be
        acknowledged. The test asserts BOTH that a DLQ persistence attempt
        was observed (else the no-ack assertion is vacuous) AND that no
        ack followed.
        """
        envelope = EventEnvelope(event="test.poison", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()

        redis = _make_redis_with_reclaim()
        redis.xautoclaim = AsyncMock(return_value=("0-0", [("entry-poison", stream_dict)], []))
        redis.xpending_range = AsyncMock(
            return_value=[
                {
                    "message_id": b"entry-poison",
                    "consumer": b"prior-consumer",
                    "time_since_delivered": 60_000,
                    "times_delivered": 99,
                }
            ]
        )
        redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
        # Track DLQ persistence attempts and fail them.
        dlq_attempts: list[object] = []

        async def failing_xadd(*args: object, **kwargs: object) -> object:
            stream_arg = args[0] if args else kwargs.get("name")
            if stream_arg != STREAM_NAME:
                dlq_attempts.append(stream_arg)
            raise RuntimeError("DLQ persistence failed")

        redis.xadd = AsyncMock(side_effect=failing_xadd)
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(side_effect=RuntimeError("permanent failure"))

        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()

        await processor.start(shutdown)

        # The implementation must have attempted to persist the dead-letter
        # outcome. Without this, "no ack" passes vacuously even when the
        # implementation has no DLQ logic at all.
        assert dlq_attempts, (
            "the implementation must attempt DLQ persistence — without an attempt, this assertion is vacuous"
        )
        redis.xack.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_dead_letter_records_after_failed_ack_are_tolerated(self) -> None:
        """Re-delivery after a failed ack must produce a SECOND dead-letter
        record AND that record must reference the same original entry
        identity — proving toleration "by original entry identity."
        """
        envelope = EventEnvelope(event="test.poison-dup", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()
        original_entry_id = "entry-poison-DUP-7777"

        redis = _make_redis_with_reclaim()
        redis.xautoclaim = AsyncMock(
            side_effect=[
                ("0-0", [(original_entry_id, stream_dict)], []),
                ("0-0", [(original_entry_id, stream_dict)], []),
                ("0-0", [], []),
            ]
        )
        redis.xpending_range = AsyncMock(
            return_value=[
                {
                    "message_id": original_entry_id.encode(),
                    "consumer": b"prior-consumer",
                    "time_since_delivered": 60_000,
                    "times_delivered": 99,
                }
            ]
        )
        redis.xreadgroup = AsyncMock(side_effect=[[], [], asyncio.CancelledError()])

        ack_calls: list[object] = []

        async def xack_side_effect(*_args: object, **_kwargs: object) -> None:
            ack_calls.append(object())
            if len(ack_calls) == 1:
                # First ack fails (Redis blip). Entry stays pending; next
                # sweep reclaims it and produces a duplicate DLQ record.
                raise RuntimeError("ack blip")

        redis.xack = AsyncMock(side_effect=xack_side_effect)
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(side_effect=RuntimeError("permanent failure"))

        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()

        with _configured_event_producer():
            await processor.start(shutdown)

        # Two DLQ records were produced (the duplicate)…
        dlq_outputs = [call for call in redis.xadd.await_args_list if call.args and call.args[0] != processor._stream]
        assert len(dlq_outputs) >= 2, (
            f"duplicate-DLQ recovery must produce a second DLQ record; got {len(dlq_outputs)} DLQ writes"
        )
        # …and each duplicate references the same original entry identity.
        for call in dlq_outputs:
            payload_text = _flatten_to_string([call.args, call.kwargs])
            assert original_entry_id in payload_text, (
                f"each duplicate DLQ record must reference the original entry id "
                f"{original_entry_id!r}; saw {payload_text!r}"
            )

    @pytest.mark.asyncio
    async def test_does_not_acknowledge_when_observable_signal_fails(self) -> None:
        """The criterion: ack waits for "the dead-letter record AND its
        observable signal." This test isolates the SIGNAL half: DLQ
        persistence succeeds, but the in-band signal emission fails. The
        entry must NOT be acknowledged.
        """
        envelope = EventEnvelope(event="test.poison.signal", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()

        producer_mock = MagicMock()
        producer_mock.emit = AsyncMock(side_effect=RuntimeError("signal emission failed"))
        original_producer = _producer_module._PRODUCER_STATE.get("producer")
        _producer_module._PRODUCER_STATE["producer"] = producer_mock
        try:
            redis = _make_redis_with_reclaim()
            redis.xautoclaim = AsyncMock(return_value=("0-0", [("entry-poison", stream_dict)], []))
            redis.xpending_range = AsyncMock(
                return_value=[
                    {
                        "message_id": b"entry-poison",
                        "consumer": b"prior-consumer",
                        "time_since_delivered": 60_000,
                        "times_delivered": 99,
                    }
                ]
            )
            redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
            # DLQ persistence succeeds (xadd to non-input destination returns OK).
            redis.xadd = AsyncMock(return_value=b"dlq-1")
            pipeline = MagicMock()
            pipeline.execute = AsyncMock(side_effect=RuntimeError("permanent failure"))

            processor = EventProcessor(redis, pipeline)
            shutdown = asyncio.Event()
            shutdown.set()

            await processor.start(shutdown)

            # Isolate the signal-half: prove DLQ persistence WAS observed
            # AND the signal WAS attempted, then assert no ack followed.
            dlq_persisted = any(call.args and call.args[0] != processor._stream for call in redis.xadd.await_args_list)
            signal_attempted = producer_mock.emit.await_count > 0
            assert dlq_persisted, (
                "the implementation must persist the DLQ record before this "
                "assertion is meaningful — without persistence, no-ack passes vacuously"
            )
            assert signal_attempted, (
                "the implementation must attempt the in-band signal — without an attempt, no-ack passes vacuously"
            )
            redis.xack.assert_not_called()
        finally:
            _producer_module._PRODUCER_STATE["producer"] = original_producer

    @pytest.mark.asyncio
    async def test_does_not_acknowledge_when_event_producer_is_not_configured(self) -> None:
        """Missing producer configuration is a signal failure and must not ack."""
        envelope = EventEnvelope(event="test.poison.no-producer", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()
        original_producer = _producer_module._PRODUCER_STATE.get("producer")
        _producer_module._PRODUCER_STATE["producer"] = None
        try:
            redis = _make_redis_with_reclaim()
            redis.xautoclaim = AsyncMock(return_value=("0-0", [("entry-no-producer", stream_dict)], []))
            redis.xpending_range = AsyncMock(
                return_value=[
                    {
                        "message_id": b"entry-no-producer",
                        "consumer": b"prior-consumer",
                        "time_since_delivered": 60_000,
                        "times_delivered": 99,
                    }
                ]
            )
            redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
            redis.xadd = AsyncMock(return_value=b"dlq-1")
            pipeline = MagicMock()
            pipeline.execute = AsyncMock(side_effect=RuntimeError("permanent failure"))

            processor = EventProcessor(redis, pipeline)
            shutdown = asyncio.Event()
            shutdown.set()

            await processor.start(shutdown)

            dlq_persisted = any(call.args and call.args[0] != processor._stream for call in redis.xadd.await_args_list)
            assert dlq_persisted, "the DLQ record must be persisted before the signal step is attempted"
            redis.xack.assert_not_called()
        finally:
            _producer_module._PRODUCER_STATE["producer"] = original_producer


class TestEventProcessorObservabilitySpecs:
    """The four named metrics appear in structured-log records at state
    transitions; dead-letter growth surfaces as an in-band event.

    Verbatim requirement criterion (from `requirements.md`):

    > **Observability.** Pending depth, reclaim count, retry count, and
    > dead-letter count are exposed through structured logs at the points of
    > state transition. Dead-letter growth surfaces as an in-band event or
    > notification visible to operators.
    """

    @pytest.mark.asyncio
    async def test_named_metrics_appear_in_structured_logs_at_state_transitions(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Drive the processor through pending → reclaim → retry → DLQ
        transitions. The four metric NAMES (criterion-exact terms) must
        appear in the structured log records' attribute keys — not in a
        free-form message string.
        """
        caplog.set_level(logging.INFO, logger="teleclaude.events.processor")

        envelope = EventEnvelope(event="test.poison", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()

        redis = _make_redis_with_reclaim()
        redis.xautoclaim = AsyncMock(return_value=("0-0", [("entry-poison", stream_dict)], []))
        redis.xpending_range = AsyncMock(
            return_value=[
                {
                    "message_id": b"entry-poison",
                    "consumer": b"prior-consumer",
                    "time_since_delivered": 60_000,
                    "times_delivered": 99,
                }
            ]
        )
        redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(side_effect=RuntimeError("permanent failure"))
        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()

        with _configured_event_producer():
            await processor.start(shutdown)

        # Collect structured "extra" attribute keys + values from log records,
        # excluding standard ``LogRecord`` fields (we want STRUCTURED logging,
        # not prose).
        standard_fields = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
            "asctime",
            "message",
            "taskName",
        }
        structured_pairs: list[tuple[str, object]] = []
        for record in caplog.records:
            for key, value in record.__dict__.items():
                if key in standard_fields or key.startswith("_"):
                    continue
                structured_pairs.append((key, value))

        # Each criterion-named concept must appear as a structured field
        # whose VALUE is numeric — not just a key with a string value.
        # Where the staged transition implies a non-zero count, assert that
        # too.
        for concept, expected_min in (
            ("pending", 1),  # at least one pending entry was staged
            ("reclaim", 1),  # at least one reclaim happened
            ("retry", 1),  # the failure path retried at least once
            ("dead_letter", 1),  # the dead-letter transition occurred
        ):
            matching_numeric_values: list[int] = []
            for key, value in structured_pairs:
                if concept not in key.lower():
                    continue
                try:
                    matching_numeric_values.append(int(value))
                except (TypeError, ValueError):
                    continue
            assert matching_numeric_values, (
                f"criterion-named concept {concept!r} must appear in a structured "
                f"log field with a NUMERIC value at a state transition; got pairs "
                f"{[(k, v) for k, v in structured_pairs if concept in k.lower()]!r}"
            )
            assert any(v >= expected_min for v in matching_numeric_values), (
                f"criterion-named concept {concept!r} must reflect the staged "
                f"transition with a value >= {expected_min}; got numeric values "
                f"{matching_numeric_values!r}"
            )

    @pytest.mark.asyncio
    async def test_dead_letter_growth_in_band_event_carries_dlq_marker_and_entry_identity(
        self,
    ) -> None:
        """The criterion: "Dead-letter growth surfaces as an in-band event or
        notification visible to operators." The emitted in-band event must
        carry a DLQ/dead-letter growth semantic marker AND the original entry
        identity — operators receiving the signal need to know which entry.
        The literal event-type name is not pinned; a semantic marker (any of
        'dead', 'dlq') in the event field or payload is acceptable.
        """
        original_entry_id = "entry-grow-marker-A1B2"
        envelope = EventEnvelope(event="test.poison.growth", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()

        producer_mock = MagicMock()
        producer_mock.emit = AsyncMock(return_value="0-0")
        original_producer = _producer_module._PRODUCER_STATE.get("producer")
        _producer_module._PRODUCER_STATE["producer"] = producer_mock
        try:
            redis = _make_redis_with_reclaim()
            redis.xautoclaim = AsyncMock(return_value=("0-0", [(original_entry_id, stream_dict)], []))
            redis.xpending_range = AsyncMock(
                return_value=[
                    {
                        "message_id": original_entry_id.encode(),
                        "consumer": b"prior-consumer",
                        "time_since_delivered": 60_000,
                        "times_delivered": 99,
                    }
                ]
            )
            redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
            pipeline = MagicMock()
            pipeline.execute = AsyncMock(side_effect=RuntimeError("permanent failure"))
            processor = EventProcessor(redis, pipeline)
            shutdown = asyncio.Event()
            shutdown.set()

            await processor.start(shutdown)

            assert producer_mock.emit.await_count >= 1, (
                "dead-letter growth must surface as an in-band event via the project's notification mechanism"
            )

            # A SINGLE emission must carry BOTH the DLQ/dead-letter growth
            # semantic marker AND the original entry identity in the same
            # envelope/payload. Splitting them across emissions does not
            # satisfy the criterion — the operator-visible signal must
            # identify the entry it is about.
            correlated_emission = None
            for call in producer_mock.emit.await_args_list:
                emitted = call.args[0] if call.args else call.kwargs.get("envelope")
                if emitted is None:
                    continue
                event_field = str(getattr(emitted, "event", ""))
                payload = getattr(emitted, "payload", {})
                payload_text = _flatten_to_string([event_field, payload])
                lower = payload_text.lower()
                has_marker = "dead" in lower or "dlq" in lower
                has_entry_id = original_entry_id in payload_text
                if has_marker and has_entry_id:
                    correlated_emission = emitted
                    break

            assert correlated_emission is not None, (
                "a single in-band emission must carry BOTH the dead-letter/DLQ "
                f"growth semantic marker AND the original entry identity "
                f"{original_entry_id!r}; emissions were "
                f"{[c.args for c in producer_mock.emit.await_args_list]!r}"
            )
        finally:
            _producer_module._PRODUCER_STATE["producer"] = original_producer


class TestEventProcessorMigrationSpecs:
    """Pre-existing pending entries must be handled by the new code path.

    Verbatim requirement criterion (from `requirements.md`):

    > **Migration without flag day.** A non-empty pending entry list at
    > upgrade time is handled by the new code path without manual drain,
    > manual reset, or operator intervention. Pre-existing pending entries
    > are subject to the same recovery, retry, and dead-letter behavior as
    > new entries.
    """

    @pytest.mark.asyncio
    async def test_pre_existing_pending_entry_is_redelivered(self) -> None:
        """A pre-existing pending entry is delivered through the pipeline by
        the recovery code path — no manual drain, no manual reset.
        """
        event = _make_envelope()
        stream_dict = event.to_stream_dict()
        legacy_entry = [("legacy-entry", stream_dict)]

        redis = _make_redis_with_reclaim()
        redis.xautoclaim = AsyncMock(return_value=("0-0", legacy_entry, []))
        redis.xclaim = AsyncMock(return_value=legacy_entry)
        redis.xpending_range = AsyncMock(return_value=[])
        redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])

        pipeline = MagicMock()
        pipeline.execute = AsyncMock(return_value=event)
        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()

        await processor.start(shutdown)

        assert pipeline.execute.await_count >= 1

    @pytest.mark.asyncio
    async def test_pre_existing_pending_entry_follows_same_retry_and_dlq_behavior(
        self,
    ) -> None:
        """The criterion's exact words: pre-existing pending entries are
        "subject to the same recovery, retry, and dead-letter behavior as
        new entries." A legacy entry that fails repeatedly must reach the
        dead-letter outcome — without manual drain or reset.
        """
        envelope = EventEnvelope(event="test.legacy.poison", source="t", level=EventLevel.OPERATIONAL)
        stream_dict = envelope.to_stream_dict()
        legacy_entry_id = "legacy-poison"

        redis = _make_redis_with_reclaim()
        redis.xautoclaim = AsyncMock(return_value=("0-0", [(legacy_entry_id, stream_dict)], []))
        redis.xpending_range = AsyncMock(
            return_value=[
                {
                    "message_id": legacy_entry_id.encode(),
                    "consumer": b"prior-pid-consumer",
                    "time_since_delivered": 60_000,
                    "times_delivered": 5,
                }
            ]
        )
        redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(side_effect=RuntimeError("legacy failure"))

        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()

        await processor.start(shutdown)

        haystack_values = _collect_dlq_outputs(redis, processor._stream)
        haystack = _flatten_to_string(haystack_values)
        assert haystack_values, (
            "legacy pending entry that fails must follow the same DLQ behavior as new entries — no manual drain"
        )
        assert legacy_entry_id in haystack, "legacy entry's DLQ outcome must reference the original entry id"
