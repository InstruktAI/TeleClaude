"""Event processor — Redis Streams consumer group reader that drives the pipeline."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude.events.pipeline import Pipeline, failing_stage_from_exception
from teleclaude.events.producer import emit_event

logger = get_logger(__name__)

STREAM_NAME = "teleclaude:events"
CONSUMER_GROUP = "event-processor"


@dataclass
class _PendingEntryInfo:
    entry_id: str
    consumer_id: str | None = None
    time_since_delivered_ms: int | None = None
    times_delivered: int = 0


@dataclass
class _AttemptState:
    attempt_count: int = 0
    first_attempt_at: int | None = None
    last_attempt_at: int | None = None
    consumer_id: str | None = None
    failing_stage: str | None = None


class EventProcessor:
    """Consume events from the Redis stream and drive the system pipeline."""

    def __init__(
        self,
        redis_client: Any,
        pipeline: Pipeline,
        *,
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
        self._stream = options.get("stream") or STREAM_NAME
        self._group = options.get("group") or CONSUMER_GROUP
        self._consumer = options.get("consumer_name") or f"processor-{os.getpid()}"
        reliability = config.event_reliability
        self._idle_threshold_ms = idle_threshold_ms if idle_threshold_ms is not None else reliability.idle_threshold_ms
        self._max_attempts = max_attempts if max_attempts is not None else reliability.max_attempts
        self._sweep_interval_ms = sweep_interval_ms if sweep_interval_ms is not None else reliability.sweep_interval_ms
        self._dlq_destination = dlq_destination or reliability.dlq_destination
        self._attempts: dict[str, _AttemptState] = {}
        self._pending_info: dict[str, _PendingEntryInfo] = {}
        self._first_attempt_observed_at: int | None = None
        self._ack_failure_reclaiming = False

    def consumer_name(self) -> str:
        """Return the consumer name used for this processor instance."""
        return self._consumer

    async def start(self, shutdown_event: asyncio.Event) -> None:
        """Run the stream consumption loop until shutdown is requested."""
        if self._first_attempt_observed_at is None:
            self._first_attempt_observed_at = int(time.time())
        await self._ensure_consumer_group()
        await self._recover_pending(include_current_consumer=True)

        logger.info("EventProcessor started", stream=self._stream, group=self._group, consumer=self._consumer)

        sweep_task: asyncio.Task[None] | None = None
        if not shutdown_event.is_set():
            sweep_task = asyncio.create_task(self._run_periodic_recovery(shutdown_event), name="event-recovery-sweep")
        try:
            while not shutdown_event.is_set():
                try:
                    entries = await self._redis.xreadgroup(
                        self._group,
                        self._consumer,
                        {self._stream: ">"},
                        count=10,
                        block=1000,
                    )
                    if not entries:
                        await asyncio.sleep(0)
                        continue
                    await self._process_entries(entries)
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.exception("EventProcessor read loop error; sleeping 1s")
                    await asyncio.sleep(1.0)
        finally:
            if sweep_task is not None:
                sweep_task.cancel()
                try:
                    await sweep_task
                except asyncio.CancelledError:
                    pass

        logger.info("EventProcessor stopped")

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
        for _ in range(max(1, self._max_attempts + 1)):
            try:
                entries = await self._redis.xreadgroup(
                    self._group,
                    self._consumer,
                    {self._stream: "0"},
                    count=50,
                )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("EventProcessor current-consumer pending recovery failed")
                break
            if not entries:
                break
            logger.info("EventProcessor recovering pending entries", pending=len(entries), consumer=self._consumer)
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
        """Deserialize, execute, and acknowledge a batch of stream entries."""
        for stream, messages in entries:
            for raw_entry_id, data in messages:
                entry_id = self._decode(raw_entry_id)
                envelope: EventEnvelope | None = None
                try:
                    envelope = EventEnvelope.from_stream_dict(data)
                    await self._pipeline.execute(envelope)
                    try:
                        await self._redis.xack(self._stream, self._group, entry_id)
                    except Exception:
                        logger.exception("EventProcessor failed to ACK entry", entry_id=entry_id)
                except Exception as exc:
                    if envelope is None:
                        logger.exception("EventProcessor failed to deserialize entry", entry_id=entry_id)
                        continue
                    await self._handle_processing_failure(
                        stream=self._decode(stream),
                        entry_id=entry_id,
                        envelope=envelope,
                        exc=exc,
                    )

    async def _handle_processing_failure(
        self,
        *,
        stream: str,
        entry_id: str,
        envelope: EventEnvelope,
        exc: Exception,
    ) -> None:
        """Track a failed attempt and transition to DLQ when the ceiling is reached."""
        state = self._record_attempt(entry_id, exc)
        logger.warning(
            "event_processor_retry",
            pending=len(self._pending_info),
            retry=state.attempt_count,
            entry_id=entry_id,
            consumer=state.consumer_id or self._consumer,
        )

        if state.attempt_count < self._max_attempts:
            logger.exception("EventProcessor failed to process entry", entry_id=entry_id)
            return

        record = self._build_dead_letter_record(
            stream=stream,
            entry_id=entry_id,
            envelope=envelope,
            exc=exc,
            state=state,
        )

        try:
            await self._redis.xadd(self._dlq_destination, record)
        except Exception:
            logger.exception("EventProcessor failed to persist dead-letter record", entry_id=entry_id)
            return

        try:
            await self._emit_dead_letter_signal(record)
        except Exception:
            logger.exception("EventProcessor failed to emit dead-letter signal", entry_id=entry_id)
            return

        logger.info(
            "event_processor_dead_letter",
            pending=len(self._pending_info),
            retry=state.attempt_count,
            dead_letter=1,
            entry_id=entry_id,
            destination=self._dlq_destination,
        )
        try:
            await self._redis.xack(self._stream, self._group, entry_id)
        except Exception:
            logger.exception("EventProcessor failed to ACK dead-lettered entry", entry_id=entry_id)
            if not self._ack_failure_reclaiming:
                self._ack_failure_reclaiming = True
                try:
                    await self._reclaim_stale_pending(pending_depth=len(self._pending_info))
                finally:
                    self._ack_failure_reclaiming = False

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
        envelope: EventEnvelope,
        exc: Exception,
        state: _AttemptState,
    ) -> dict[str, str]:
        failing_stage = state.failing_stage or ""
        original_envelope = json.dumps(envelope.model_dump(mode="json"), sort_keys=True)
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
            "dlq_destination": self._dlq_destination,
        }

    async def _emit_dead_letter_signal(self, record: dict[str, str]) -> None:
        """Emit the in-band dead-letter growth signal before acknowledging."""
        await emit_event(
            "system.event.dead_lettered",
            source="event-processor",
            level=EventLevel.OPERATIONAL,
            domain="system",
            visibility=EventVisibility.CLUSTER,
            payload={
                "original_entry_id": record["original_entry_id"],
                "original_stream": record["original_stream"],
                "attempt_count": record["attempt_count"],
                "failing_stage": record["failing_stage"],
                "consumer_id": record["consumer_id"],
                "dlq_destination": record["dlq_destination"],
            },
        )

    async def _read_pending_info(self) -> dict[str, _PendingEntryInfo]:
        try:
            rows = await self._redis.xpending_range(self._stream, self._group, "-", "+", 100)
        except AttributeError:
            return {}
        except Exception:
            logger.exception("EventProcessor pending metadata read failed")
            return {}

        info_by_id: dict[str, _PendingEntryInfo] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_message_id = row.get("message_id")
            if raw_message_id is None:
                continue
            entry_id = self._decode(raw_message_id)
            info_by_id[entry_id] = _PendingEntryInfo(
                entry_id=entry_id,
                consumer_id=self._optional_decode(row.get("consumer")),
                time_since_delivered_ms=self._optional_int(row.get("time_since_delivered")),
                times_delivered=self._optional_int(row.get("times_delivered")) or 0,
            )
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
