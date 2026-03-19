"""Event processor — Redis Streams consumer group reader that drives the pipeline."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import Pipeline

logger = get_logger(__name__)

STREAM_NAME = "teleclaude:events"
CONSUMER_GROUP = "event-processor"


class EventProcessor:
    """Consume events from the Redis stream and drive the system pipeline."""

    def __init__(
        self,
        redis_client: Any,
        pipeline: Pipeline,
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

    def consumer_name(self) -> str:
        """Return the consumer name used for this processor instance."""
        return self._consumer

    async def start(self, shutdown_event: asyncio.Event) -> None:
        """Run the stream consumption loop until shutdown is requested."""
        await self._ensure_consumer_group()
        await self._recover_pending()

        logger.info("EventProcessor started", stream=self._stream, group=self._group, consumer=self._consumer)

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
                    continue
                await self._process_entries(entries)
            except asyncio.CancelledError:
                break
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("EventProcessor read loop error; sleeping 1s")
                await asyncio.sleep(1.0)

        logger.info("EventProcessor stopped")

    async def _ensure_consumer_group(self) -> None:
        """Create the Redis consumer group if it does not already exist."""
        try:
            await self._redis.xgroup_create(self._stream, self._group, id="$", mkstream=True)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if "BUSYGROUP" not in str(exc):
                raise

    async def _recover_pending(self) -> None:
        """Recover and process any pending entries already assigned to this consumer."""
        try:
            entries = await self._redis.xreadgroup(
                self._group,
                self._consumer,
                {self._stream: "0"},
                count=50,
            )
            if entries:
                logger.info("EventProcessor recovering pending entries", count=len(entries))
                await self._process_entries(entries)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("EventProcessor pending recovery failed")

    async def _process_entries(self, entries: Any) -> None:
        """Deserialize, execute, and acknowledge a batch of stream entries."""
        for _stream, messages in entries:
            for entry_id, data in messages:
                try:
                    envelope = EventEnvelope.from_stream_dict(data)
                    await self._pipeline.execute(envelope)
                    try:
                        await self._redis.xack(self._stream, self._group, entry_id)
                    except Exception:  # pylint: disable=broad-exception-caught
                        logger.exception("EventProcessor failed to ACK entry", entry_id=entry_id)
                except Exception:  # pylint: disable=broad-exception-caught
                    logger.exception("EventProcessor failed to process entry", entry_id=entry_id)
