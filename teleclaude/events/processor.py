"""Event processor — Redis Streams consumer group reader that drives the pipeline."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

from instrukt_ai_logging import get_logger
from pydantic import BaseModel

from teleclaude.config.machine import config
from teleclaude.core.models import HumanActionIntent
from teleclaude.events.envelope import EventHomeMarker, EventLevel, EventVisibility
from teleclaude.events.pipeline import failing_stage_from_exception
from teleclaude.events.producer import publish_event
from teleclaude.events.references import StreamEntryRef
from teleclaude.events.schemas.system import DeadLetteredData, EventDeadLettered
from teleclaude.events.stream_wait import STREAM_BLOCK_MS, read_until_shutdown
from teleclaude.events.wire import EntryCodec, LegacyFacts, StreamEntry

logger = get_logger(__name__)

STREAM_NAME = "teleclaude:events"
CONSUMER_GROUP = "event-processor"
#: Pause between in-place attempts at one entry in ordered mode.
ORDERED_RETRY_PAUSE_S = 1.0
_STREAM_ENTRY_IDENTITY = "{stream}/{entry_id}"
_CONSUME_TASK_NAME = "event-consume"
_RECOVERY_SWEEP_TASK_NAME = "event-recovery-sweep"
_RECOVERY_SWEEP_ENDED = "The stale-pending recovery sweep ended while the processor was running"
_PENDING_PAGE_SIZE = 100
_PENDING_READ_BATCH_SIZE = 50
_JSON_SERIALIZATION_MODE = "json"


class RecoverySweepEnded(Exception):
    """The stale-pending recovery sweep returned while its processor was still running, so the processor's run ends."""


class StreamEntryPipeline[DecodedT](Protocol):
    """Execute one decoded entry read from an event stream."""

    async def execute(self, event: DecodedT, /) -> object: ...


@dataclass
class _PendingEntryInfo:
    entry_id: str
    consumer_id: str | None = None
    time_since_delivered_ms: int | None = None
    times_delivered: int = 0


@dataclass
class _ParkedEntry:
    """An entry that reached the attempt ceiling: its dead-letter record and which parking steps are done."""

    record: dict[str, str]
    failed_event_id: str | None
    persisted: bool = False
    announced: bool = False


@dataclass
class _AttemptState:
    attempt_count: int = 0
    first_attempt_at: int | None = None
    last_attempt_at: int | None = None
    consumer_id: str | None = None
    failing_stage: str | None = None
    parked: _ParkedEntry | None = None


class EventProcessor[DecodedT: BaseModel]:
    """Consume entries from a Redis stream, decode each with the stream's codec, and drive its pipeline.

    By default a failed entry stays pending and is retried through stale-pending reclaim while later
    entries continue. In ordered mode the reader owns its group alone under a stable reader name: a
    failed entry is attempted again in place until the attempt ceiling, then dead-lettered, and no
    later entry is read first, so handling stays in stream order and a parked entry blocks nothing.
    """

    def __init__(
        self,
        redis_client: Any,
        pipeline: StreamEntryPipeline[DecodedT],
        *,
        codec: EntryCodec[DecodedT],
        declared_name: str,
        ordered: bool = False,
        idle_threshold_ms: int | None = None,
        max_attempts: int | None = None,
        sweep_interval_ms: int | None = None,
        dlq_destination: str | None = None,
        **options: str | None,
    ) -> None:
        """Initialize the processor with Redis stream and consumer-group settings."""
        unexpected_options = sorted(set(options) - {"stream", "group", "consumer_name"})
        if unexpected_options:
            unexpected = ", ".join(unexpected_options)
            raise TypeError(f"Unsupported EventProcessor options: {unexpected}")
        self._redis = redis_client
        self._pipeline = pipeline
        self._codec = codec
        self._stream = options.get("stream") or STREAM_NAME
        self._group = options.get("group") or CONSUMER_GROUP
        self._consumer = options.get("consumer_name") or f"processor-{os.getpid()}"
        self._declared_name = declared_name
        self._ordered = ordered
        self._shutdown_event: asyncio.Event | None = None
        reliability = config.event_reliability
        self._idle_threshold_ms = idle_threshold_ms if idle_threshold_ms is not None else reliability.idle_threshold_ms
        self._max_attempts = max_attempts if max_attempts is not None else reliability.max_attempts
        self._sweep_interval_ms = sweep_interval_ms if sweep_interval_ms is not None else reliability.sweep_interval_ms
        self._dlq_destination = dlq_destination or reliability.dlq_destination
        self._attempts: dict[str, _AttemptState] = {}
        self._pending_info: dict[str, _PendingEntryInfo] = {}
        self._first_attempt_observed_at: int | None = None
        self._ack_failure_reclaiming = False
        self._group_position_prepared = False

    def consumer_name(self) -> str:
        """Return the consumer name used for this processor instance."""
        return self._consumer

    async def prepare_group_position(self) -> None:
        """Idempotently establish this reader's Redis group position without executing any entries."""
        if self._group_position_prepared:
            return
        await self._ensure_consumer_group()
        self._group_position_prepared = True

    async def start(self, shutdown_event: asyncio.Event) -> None:
        """Run the stream consumption loop until shutdown is requested."""
        if self._first_attempt_observed_at is None:
            self._first_attempt_observed_at = int(time.time())
        self._shutdown_event = shutdown_event
        await self.prepare_group_position()
        await self._recover_pending(include_current_consumer=True)

        logger.info(
            "EventProcessor started",
            stream=self._stream,
            group=self._group,
            consumer=self._consumer,
            name=self._declared_name,
            ordered=self._ordered,
        )

        # The read loop and the recovery sweep are one unit: either ending while the processor runs ends the run.
        async with asyncio.TaskGroup() as group:
            group.create_task(self._read_until_shutdown(shutdown_event), name=_CONSUME_TASK_NAME)
            if not shutdown_event.is_set() and not self._ordered:
                group.create_task(self._sweep_until_shutdown(shutdown_event), name=_RECOVERY_SWEEP_TASK_NAME)

        logger.info("EventProcessor stopped")

    async def _read_until_shutdown(self, shutdown_event: asyncio.Event) -> None:
        """Read and process stream entries until shutdown is requested."""
        while not shutdown_event.is_set():
            try:
                entries = await read_until_shutdown(
                    self._redis.xreadgroup(
                        self._group,
                        self._consumer,
                        {self._stream: ">"},
                        count=10,
                        block=STREAM_BLOCK_MS,
                    ),
                    shutdown_event,
                )
                if not entries:
                    await asyncio.sleep(0)
                    continue
                await self._process_entries(entries)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("EventProcessor read loop error; sleeping 1s")
                if self._ordered:
                    raise
                await asyncio.sleep(1.0)

    async def _sweep_until_shutdown(self, shutdown_event: asyncio.Event) -> None:
        """Run the periodic recovery sweep; its return before shutdown is an end of the processor's run."""
        await self._run_periodic_recovery(shutdown_event)
        if not shutdown_event.is_set():
            raise RecoverySweepEnded(_RECOVERY_SWEEP_ENDED)

    async def _ensure_consumer_group(self) -> None:
        """Create the Redis consumer group if it does not already exist."""
        try:
            await self._redis.xgroup_create(self._stream, self._group, id="$", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _recover_pending(self, *, include_current_consumer: bool = True) -> None:
        """Recover and process pending entries assigned to this or stale consumers."""
        self._pending_info = await self._read_pending_info()
        pending_depth = len(self._pending_info)
        logger.debug("event_processor_pending", pending=pending_depth, stream=self._stream, group=self._group)

        if include_current_consumer:
            await self._recover_current_consumer_pending()

        if not self._ordered:
            await self._reclaim_stale_pending(pending_depth=pending_depth)

    async def _run_periodic_recovery(self, shutdown_event: asyncio.Event) -> None:
        """Run stale-pending recovery at the configured sweep cadence."""
        interval_seconds = max(1, self._sweep_interval_ms) / 1000
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass
            except asyncio.CancelledError:
                raise

            if shutdown_event.is_set():
                break
            try:
                await self._recover_pending(include_current_consumer=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("EventProcessor periodic pending recovery failed")

    async def _recover_current_consumer_pending(self) -> None:
        """Recover pending entries already assigned to this consumer."""
        while True:
            try:
                entries = await self._redis.xreadgroup(
                    self._group,
                    self._consumer,
                    {self._stream: "0"},
                    count=_PENDING_READ_BATCH_SIZE,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("EventProcessor current-consumer pending recovery failed")
                if self._ordered:
                    raise
                return
            pending_count = sum(len(messages) for _, messages in entries)
            if not pending_count:
                return
            logger.info("EventProcessor recovering pending entries", pending=pending_count, consumer=self._consumer)
            await self._process_entries(entries)

    async def _reclaim_stale_pending(self, *, pending_depth: int) -> None:
        """Reclaim stale pending entries from any consumer."""
        try:
            result = await self._redis.xautoclaim(
                self._stream,
                self._group,
                self._consumer,
                self._idle_threshold_ms,
                "0-0",
                count=50,
            )
        except AttributeError:
            result = ("0-0", [], [])
        except Exception:
            logger.exception("EventProcessor stale pending reclaim failed")
            return

        messages = self._extract_claimed_messages(result)
        if not messages:
            return

        logger.info(
            "event_processor_reclaim",
            pending=pending_depth,
            reclaim=len(messages),
            idle_threshold_ms=self._idle_threshold_ms,
            consumer=self._consumer,
        )
        await self._process_entries([(self._stream, messages)])

    async def _process_entries(self, entries: Any) -> None:
        """Deserialize, execute, and acknowledge a batch of stream entries, one after the other."""
        for stream, messages in entries:
            for raw_entry_id, data in messages:
                entry_id = self._decode(raw_entry_id)
                if self._ordered:
                    await self._process_entry_in_order(self._decode(stream), entry_id, data)
                else:
                    await self._process_entry(self._decode(stream), entry_id, data)

    async def _process_entry_in_order(self, stream: str, entry_id: str, data: StreamEntry) -> None:
        """Attempt one entry until it is handled or parked; an entry left unsettled is attempted again first."""
        while not await self._attempt_in_order(stream, entry_id, data):
            if self._shutdown_event is not None and self._shutdown_event.is_set():
                return
            await self._pause_before_next_attempt()
        self._attempts.pop(entry_id, None)

    async def _attempt_in_order(self, stream: str, entry_id: str, data: StreamEntry) -> bool:
        """Run the entry through the pipeline, or, once it reached the ceiling, finish parking it without the handler."""
        state = self._attempts.get(entry_id)
        if state is not None and state.parked is not None:
            return await self._complete_parking(entry_id, state)
        return await self._process_entry(stream, entry_id, data)

    async def _pause_before_next_attempt(self) -> None:
        """Wait between in-place attempts; shutdown ends the wait early."""
        if self._shutdown_event is None:
            await asyncio.sleep(ORDERED_RETRY_PAUSE_S)
            return
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=ORDERED_RETRY_PAUSE_S)
        except TimeoutError:
            pass

    async def _process_entry(self, stream: str, entry_id: str, data: StreamEntry) -> bool:
        """Run one entry through the pipeline; ordered decode failures settle through parking."""
        decoded: DecodedT | None = None
        try:
            decoded = self._codec.decode(data, entry_id)
            await self._pipeline.execute(decoded)
        except Exception as exc:
            if decoded is None:
                logger.exception("EventProcessor failed to deserialize entry", entry_id=entry_id)
                if not self._ordered:
                    return True
            return await self._handle_processing_failure(
                stream=stream,
                entry_id=entry_id,
                decoded=decoded,
                raw_entry=data,
                exc=exc,
            )
        try:
            await self._redis.xack(self._stream, self._group, entry_id)
        except Exception:
            logger.exception("EventProcessor failed to ACK entry", entry_id=entry_id)
            if self._ordered:
                raise
        return True

    async def _handle_processing_failure(
        self,
        *,
        stream: str,
        entry_id: str,
        decoded: DecodedT | None,
        raw_entry: StreamEntry,
        exc: Exception,
    ) -> bool:
        """Track a failed attempt and transition to DLQ when the ceiling is reached.

        Returns whether the entry is settled (parked); an entry left pending below the ceiling, or
        whose parking is not finished, is not.
        """
        state = self._record_attempt(entry_id, exc)
        logger.warning(
            "event_processor_retry",
            pending=len(self._pending_info),
            retry=state.attempt_count,
            entry_id=entry_id,
            consumer=state.consumer_id or self._consumer,
            name=self._declared_name,
        )

        if state.attempt_count < self._max_attempts:
            logger.exception("EventProcessor failed to process entry", entry_id=entry_id)
            return False

        if state.parked is None:
            state.parked = _ParkedEntry(
                record=self._build_dead_letter_record(
                    stream=stream,
                    entry_id=entry_id,
                    decoded=decoded,
                    raw_entry=raw_entry,
                    exc=exc,
                    state=state,
                ),
                failed_event_id=self._codec.event_id(decoded) if decoded is not None else None,
            )
        return await self._complete_parking(entry_id, state)

    async def _complete_parking(self, entry_id: str, state: _AttemptState) -> bool:
        """Persist the dead-letter record, announce it, and acknowledge the entry; each step is done once.

        Returns whether the entry is settled. A step that fails leaves the earlier ones recorded, so a
        later call repeats only what remains and never writes a second record.
        """
        parked = state.parked
        assert parked is not None  # set by _handle_processing_failure before parking
        if not parked.persisted:
            try:
                await self._redis.xadd(self._dlq_destination, parked.record)
            except Exception:
                logger.exception("EventProcessor failed to persist dead-letter record", entry_id=entry_id)
                return False
            parked.persisted = True

        if not parked.announced:
            try:
                await self._emit_dead_letter_signal(parked.record, parked.failed_event_id)
            except Exception:
                logger.exception("EventProcessor failed to emit dead-letter signal", entry_id=entry_id)
                return False
            parked.announced = True

        logger.info(
            "event_processor_dead_letter",
            pending=len(self._pending_info),
            retry=state.attempt_count,
            dead_letter=1,
            entry_id=entry_id,
            destination=self._dlq_destination,
            name=self._declared_name,
        )
        try:
            await self._redis.xack(self._stream, self._group, entry_id)
        except Exception:
            logger.exception("EventProcessor failed to ACK dead-lettered entry", entry_id=entry_id)
            if self._ordered:
                return False
            if not self._ordered and not self._ack_failure_reclaiming:
                self._ack_failure_reclaiming = True
                try:
                    await self._reclaim_stale_pending(pending_depth=len(self._pending_info))
                finally:
                    self._ack_failure_reclaiming = False
        return True

    def _record_attempt(self, entry_id: str, exc: Exception) -> _AttemptState:
        info = self._pending_info.get(entry_id)
        state = self._attempts.setdefault(entry_id, _AttemptState())
        baseline = info.times_delivered if info is not None else 0
        if state.first_attempt_at is None:
            state.first_attempt_at = self._first_attempt_observed_at or int(time.time())
        state.attempt_count = max(state.attempt_count, baseline) + 1
        state.last_attempt_at = int(time.time())
        state.consumer_id = info.consumer_id if info is not None and info.consumer_id else self._consumer
        failing_stage = failing_stage_from_exception(exc)
        state.failing_stage = failing_stage or state.failing_stage
        return state

    def _build_dead_letter_record(
        self,
        *,
        stream: str,
        entry_id: str,
        decoded: DecodedT | None,
        raw_entry: StreamEntry,
        exc: Exception,
        state: _AttemptState,
    ) -> dict[str, str]:
        failing_stage = state.failing_stage or ""
        if decoded is None:
            original_envelope = json.dumps(
                {self._decode(key): self._decode(value) for key, value in raw_entry.items()},
                sort_keys=True,
            )
        else:
            original_envelope = json.dumps(decoded.model_dump(mode=_JSON_SERIALIZATION_MODE), sort_keys=True)
        return {
            "original_envelope": original_envelope,
            "original_stream": stream or self._stream,
            "original_entry_id": entry_id,
            "attempt_count": str(state.attempt_count),
            "failure_type": type(exc).__name__,
            "failure_message": str(exc),
            "failing_stage": failing_stage,
            "first_attempt_at": str(state.first_attempt_at or ""),
            "last_attempt_at": str(state.last_attempt_at or ""),
            "consumer_id": state.consumer_id or self._consumer,
            "consumer": self._declared_name,
            "dlq_destination": self._dlq_destination,
        }

    async def _emit_dead_letter_signal(self, record: dict[str, str], failed_event_id: str | None) -> None:
        """Emit the in-band dead-letter growth signal before acknowledging."""
        await publish_event(
            EventDeadLettered(
                subject=StreamEntryRef(
                    _STREAM_ENTRY_IDENTITY.format(
                        stream=record["original_stream"], entry_id=record["original_entry_id"]
                    )
                ),
                home=EventHomeMarker.NONE,
                data=DeadLetteredData(
                    original_entry_id=record["original_entry_id"],
                    original_stream=record["original_stream"],
                    attempt_count=record["attempt_count"],
                    failing_stage=record["failing_stage"],
                    consumer_id=record["consumer_id"],
                    consumer=record["consumer"],
                    dlq_destination=record["dlq_destination"],
                ),
                causationid=failed_event_id,
            ),
            LegacyFacts(
                producer="event-processor",
                level=EventLevel.OPERATIONAL,
                domain="system",
                visibility=EventVisibility.CLUSTER,
                human_action=HumanActionIntent(
                    topic="Dead-letter queue requires attention",
                    summary="An event exhausted its retries.",
                    action="Inspect the dead-letter destination",
                ),
            ),
        )

    async def _read_pending_info(self) -> dict[str, _PendingEntryInfo]:
        info_by_id: dict[str, _PendingEntryInfo] = {}
        cursor = "-"
        while True:
            try:
                rows = await self._redis.xpending_range(
                    self._stream,
                    self._group,
                    cursor,
                    "+",
                    _PENDING_PAGE_SIZE,
                )
            except AttributeError:
                if self._ordered:
                    raise RuntimeError("Ordered EventProcessor requires paged pending metadata support") from None
                return info_by_id
            except Exception:
                logger.exception("EventProcessor pending metadata read failed")
                if self._ordered:
                    raise
                return info_by_id

            if not rows:
                break
            last_id: str | None = None
            for row in rows:
                if not isinstance(row, dict):
                    continue
                raw_message_id = row.get("message_id")
                if raw_message_id is None:
                    continue
                entry_id = self._decode(raw_message_id)
                last_id = entry_id
                info_by_id[entry_id] = _PendingEntryInfo(
                    entry_id=entry_id,
                    consumer_id=self._optional_decode(row.get("consumer")),
                    time_since_delivered_ms=self._optional_int(row.get("time_since_delivered")),
                    times_delivered=self._optional_int(row.get("times_delivered")) or 0,
                )
            if last_id is None or len(rows) < _PENDING_PAGE_SIZE:
                break
            cursor = f"({last_id}"
        return info_by_id

    def _extract_claimed_messages(self, result: object) -> list[tuple[object, object]]:
        if not isinstance(result, tuple) or len(result) < 2:
            return []
        messages = result[1]
        if not isinstance(messages, list):
            return []
        claimed: list[tuple[object, object]] = []
        for item in messages:
            if isinstance(item, tuple) and len(item) == 2:
                claimed.append((item[0], item[1]))
        return claimed

    def _decode(self, value: object) -> str:
        if isinstance(value, bytes):
            return value.decode()
        return str(value)

    def _optional_decode(self, value: object) -> str | None:
        if value is None:
            return None
        return self._decode(value)

    def _optional_int(self, value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, bytes):
            value = value.decode()
        if not isinstance(value, str):
            return None
        try:
            return int(value)
        except ValueError:
            return None
