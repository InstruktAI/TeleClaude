"""Event processor — Redis Streams consumer group reader that drives the pipeline."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude_events.envelope import EventEnvelope
from teleclaude_events.pipeline import Pipeline

logger = get_logger(__name__)

STREAM_NAME = "teleclaude:events"
CONSUMER_GROUP = "event-processor"


class EventProcessor:
    def __init__(
        self,
        redis_client: Any,
        pipeline: Pipeline,
        stream: str = STREAM_NAME,
        group: str = CONSUMER_GROUP,
        consumer_name: str | None = None,
    ) -> None:
        self._redis = redis_client
        self._pipeline = pipeline
        self._stream = stream
        self._group = group
        self._consumer = consumer_name or f"processor-{os.getpid()}"

    async def start(self, shutdown_event: asyncio.Event) -> None:
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
        try:
            await self._redis.xgroup_create(self._stream, self._group, id="$", mkstream=True)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if "BUSYGROUP" not in str(exc):
                raise

    async def _recover_pending(self) -> None:
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
        for _stream, messages in entries:
            for entry_id, data in messages:
                try:
                    envelope = EventEnvelope.from_stream_dict(data)
                    await self._pipeline.execute(envelope)
                except Exception:  # pylint: disable=broad-exception-caught
                    logger.exception("EventProcessor failed to process entry", entry_id=entry_id)
                finally:
                    try:
                        await self._redis.xack(self._stream, self._group, entry_id)
                    except Exception:  # pylint: disable=broad-exception-caught
                        logger.exception("EventProcessor failed to ACK entry", entry_id=entry_id)
