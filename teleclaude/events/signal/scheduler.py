"""Ingest scheduler — background loop that periodically triggers the ingest cartridge."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from teleclaude.events.pipeline import PipelineContext

logger = logging.getLogger(__name__)

def _resolve_pull(cartridge: object) -> Callable[["PipelineContext"], Awaitable[int]]:
    """Return the cartridge pull method after validating it exists."""
    pull = getattr(cartridge, "pull", None)
    if not callable(pull):
        raise TypeError("IngestScheduler cartridge must expose a callable pull(context) method")
    return cast(Callable[["PipelineContext"], Awaitable[int]], pull)


class IngestScheduler:
    """Runs ingest pulls on a fixed interval until the shutdown event is set."""

    def __init__(self, cartridge: object, context: PipelineContext, interval_seconds: int) -> None:
        """Initialize the scheduler with a pull-capable cartridge and interval."""
        self._pull = _resolve_pull(cartridge)
        self._context = context
        self._interval = interval_seconds

    def interval_seconds(self) -> int:
        """Return the configured polling interval in seconds."""
        return self._interval

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Run the periodic ingest loop until the shutdown event is set."""
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
                count = await self._pull(self._context)
                logger.info("IngestScheduler: pulled %d new items", count)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("IngestScheduler pull failed: %s", e, exc_info=True)

        logger.info("IngestScheduler stopped")
