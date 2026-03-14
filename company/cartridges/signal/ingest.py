"""Signal ingest cartridge — pulls feeds, enriches items, emits signal.ingest.received."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude.events.signal.ai import SignalAIClient
from teleclaude.events.signal.db import SignalDB
from teleclaude.events.signal.fetch import fetch_url, parse_rss_feed
from teleclaude.events.signal.sources import SignalSourceConfig, SourceType, load_sources

if TYPE_CHECKING:
    from teleclaude.events.pipeline import PipelineContext

logger = logging.getLogger(__name__)


def _build_idempotency_key(source_id: str, item_url: str) -> str:
    return f"signal.ingest.received:{source_id}:{item_url}"


class SignalIngestCartridge:
    name = "signal-ingest"

    def __init__(self, config: SignalSourceConfig, ai: SignalAIClient, signal_db: SignalDB) -> None:
        self._config = config
        self._ai = ai
        self._signal_db = signal_db

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        # Only acts on the scheduler trigger; all other events pass through unchanged.
        if event.event != "signal.pull.triggered":
            return event
        await self.pull(context)
        return None

    async def pull(self, context: PipelineContext) -> int:
        """Explicit pull — returns count of new items ingested."""
        sources = await load_sources(self._config)
        sem = asyncio.Semaphore(self._config.ai_concurrency)
        count = 0

        for source in sources:
            if source.type not in (SourceType.RSS, SourceType.YOUTUBE):
                logger.debug("Skipping unsupported source type: %s (%s)", source.type, source.label)
                continue
            if not source.url:
                continue
            source_id = source.label or source.url or ""

            result = await fetch_url(source.url)
            if result.error or result.body is None:
                logger.warning("Failed to fetch feed %s: %s", source.url, result.error)
                continue

            items = parse_rss_feed(result.body)
            if not items and result.body:
                logger.warning("Feed %s: non-empty body produced zero items", source.url)
            new_items = []
            for item in items[: self._config.max_items_per_pull]:
                ikey = _build_idempotency_key(source.label or source.url, item["url"])
                if not await self._signal_db.signal_item_exists(ikey):
                    new_items.append((ikey, item))

            # Enrich new items concurrently
            async def enrich_and_emit(ikey: str, item: dict, *, source_id: str = source_id) -> None:  # type: ignore[type-arg]
                nonlocal count
                async with sem:
                    summary = await self._ai.summarise(item.get("title", ""), item.get("description", ""))
                    tags = await self._ai.extract_tags(item.get("title", ""), summary)
                    embed = await self._ai.embed(summary)

                fetched_at = datetime.now(UTC).isoformat()
                payload: dict[str, object] = {
                    "idempotency_key": ikey,
                    "source_id": source_id,
                    "item_url": item.get("url", ""),
                    "raw_title": item.get("title", ""),
                    "tags": tags,
                    "published_at": item.get("published", ""),
                    "fetched_at": fetched_at,
                    "summary": summary,
                    "embedding": embed,
                }
                row_id = await self._signal_db.insert_signal_item(payload)  # type: ignore[arg-type]
                if row_id == 0:
                    # Already inserted by a concurrent call (race); skip
                    return

                envelope = EventEnvelope(
                    event="signal.ingest.received",
                    source=source_id,
                    level=EventLevel.OPERATIONAL,
                    domain="signal",
                    visibility=EventVisibility.LOCAL,
                    description=summary,
                    idempotency_key=ikey,
                    payload={
                        "source_id": source_id,
                        "item_url": item.get("url", ""),
                        "raw_title": item.get("title", ""),
                        "tags": tags,
                        "published_at": item.get("published", ""),
                        "fetched_at": fetched_at,
                    },
                )
                if context.emit:
                    await context.emit(envelope)
                count += 1

            tasks = [enrich_and_emit(ikey, item) for ikey, item in new_items]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r, (ikey, item) in zip(results, new_items):
                if isinstance(r, Exception):
                    logger.error(
                        "Ingest enrichment error for %s (%s): %s",
                        ikey,
                        item.get("url", ""),
                        r,
                        exc_info=True,
                    )

        return count
