"""Ingest scheduler — background loop that periodically triggers the ingest cartridge."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.events.pipeline import PipelineContext

logger = logging.getLogger(__name__)


class IngestScheduler:
    """Runs ingest pulls on a fixed interval until the shutdown event is set."""

    def __init__(self, cartridge: object, context: PipelineContext, interval_seconds: int) -> None:
        self._cartridge = cartridge
        self._context = context
        self._interval = interval_seconds

    async def run(self, shutdown_event: asyncio.Event) -> None:
        logger.info("IngestScheduler started (interval=%ds)", self._interval)
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=self._interval)
                # shutdown_event was set
                break
            except TimeoutError:
                pass

            if shutdown_event.is_set():
                break

            try:
                count = await self._cartridge.pull(self._context)  # type: ignore
                logger.info("IngestScheduler: pulled %d new items", count)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("IngestScheduler pull failed: %s", e, exc_info=True)

        logger.info("IngestScheduler stopped")
