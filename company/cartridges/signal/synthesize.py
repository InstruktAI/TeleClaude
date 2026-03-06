"""Signal synthesize cartridge — synthesises clusters into structured artifacts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel

from teleclaude_events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude_events.signal.ai import SignalAIClient
from teleclaude_events.signal.db import SignalDB
from teleclaude_events.signal.fetch import fetch_full_content

if TYPE_CHECKING:
    from teleclaude_events.pipeline import PipelineContext

logger = logging.getLogger(__name__)


class SynthesizeConfig(BaseModel):
    max_items_per_cluster: int = 10
    max_content_chars_per_item: int = 8000
    fetch_full_content: bool = True


def _near_duplicate(summary_a: str, summary_b: str, threshold: float = 0.9) -> bool:
    """Simple word-overlap dedup heuristic."""
    words_a = set(summary_a.lower().split())
    words_b = set(summary_b.lower().split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b) / max(len(words_a), len(words_b))
    return overlap >= threshold


class SignalSynthesizeCartridge:
    name = "signal-synthesize"

    def __init__(self, config: SynthesizeConfig, ai: SignalAIClient, signal_db: SignalDB) -> None:
        self._config = config
        self._ai = ai
        self._signal_db = signal_db

    async def process(self, event: EventEnvelope, context: "PipelineContext") -> EventEnvelope | None:
        if event.event != "signal.cluster.formed":
            return event

        cluster_id = event.payload.get("cluster_id")
        if cluster_id is None:
            logger.warning("signal.cluster.formed event missing cluster_id; passing through")
            return event

        members = await self._signal_db.get_cluster_members(
            int(cluster_id), limit=self._config.max_items_per_cluster
        )
        if not members:
            logger.warning("Cluster %s has no members; skipping synthesis", cluster_id)
            return event

        # Optionally fetch full content
        enriched: list[dict[str, object]] = []
        for item in members:
            d = dict(item)
            if self._config.fetch_full_content:
                url = str(d.get("item_url", ""))
                if url:
                    full = await fetch_full_content(url, self._config.max_content_chars_per_item)
                    if full:
                        d["full_content"] = full
            enriched.append(d)

        # Cross-source dedup: remove near-identical summaries
        deduped: list[dict[str, object]] = []
        seen_summaries: list[str] = []
        for item in enriched:
            summary = str(item.get("summary", ""))
            if any(_near_duplicate(summary, s) for s in seen_summaries):
                continue
            seen_summaries.append(summary)
            deduped.append(item)

        try:
            artifact = await self._ai.synthesise_cluster(deduped)
        except Exception as e:
            logger.error("Synthesis failed for cluster %s: %s", cluster_id, e, exc_info=True)
            return event
        artifact_dict = artifact.model_dump()
        await self._signal_db.insert_synthesis(int(cluster_id), artifact_dict)

        description = artifact.summary[:200]
        return EventEnvelope(
            event="signal.synthesis.ready",
            source="signal-synthesize",
            level=EventLevel.WORKFLOW,
            domain="signal",
            visibility=EventVisibility.LOCAL,
            description=description,
            idempotency_key=f"signal.synthesis.ready:{cluster_id}",
            payload={
                "cluster_id": cluster_id,
                "synthesis": artifact_dict,
            },
        )
