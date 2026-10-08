"""Signal synthesize cartridge — synthesises clusters into structured artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from pydantic import BaseModel

from teleclaude.events.envelope import EventHomeMarker, EventLevel, EventVisibility, occurrence_id
from teleclaude.events.references import SignalSynthesisRef
from teleclaude.events.schemas.signal import SignalSynthesisReady, SignalSynthesisReadyData
from teleclaude.events.signal.ai import SignalAIClient
from teleclaude.events.signal.db import SignalDB
from teleclaude.events.signal.fetch import fetch_full_content
from teleclaude.events.wire import LegacyFacts, StreamEvent

if TYPE_CHECKING:
    from teleclaude.events.pipeline import PipelineContext

logger = get_logger(__name__)


class SynthesizeConfig(BaseModel):
    """Configuration for the signal synthesis cartridge."""

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
    """Cartridge that synthesizes cluster items into digest summaries."""

    name = "signal-synthesize"

    def describe(self) -> str:
        """Return cartridge name."""
        return self.name

    def __init__(self, config: SynthesizeConfig, ai: SignalAIClient, signal_db: SignalDB) -> None:
        self._config = config
        self._ai = ai
        self._signal_db = signal_db

    async def process(self, event: StreamEvent, context: PipelineContext) -> StreamEvent | None:
        """Synthesize cluster items into a digest summary."""
        if event.type != "teleclaude.signal.cluster.formed":
            return event

        cluster_id = event.data.get("cluster_id")
        if not isinstance(cluster_id, int):
            logger.warning("signal.cluster.formed event missing cluster_id; passing through")
            return event

        members = await self._signal_db.get_cluster_members(cluster_id, limit=self._config.max_items_per_cluster)
        if not members:
            logger.warning("Cluster %s has no members; skipping synthesis", cluster_id)
            return event

        # Optionally fetch full content
        enriched: list[dict[str, object]] = []  # guard: loose-dict - enriched signal items
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
        deduped: list[dict[str, object]] = []  # guard: loose-dict - deduped signal items
        seen_summaries: list[str] = []
        for item in enriched:  # type: ignore[assignment]
            summary = str(item.get("summary", ""))
            if any(_near_duplicate(summary, s) for s in seen_summaries):
                continue
            seen_summaries.append(summary)
            deduped.append(item)  # type: ignore[arg-type]

        try:
            artifact = await self._ai.synthesise_cluster(deduped)  # type: ignore[arg-type]
        except Exception as e:
            logger.error("Synthesis failed for cluster %s: %s", cluster_id, e, exc_info=True)
            return event
        artifact_dict = artifact.model_dump()
        await self._signal_db.insert_synthesis(cluster_id, artifact_dict)

        if context.producer is None:
            logger.warning("signal synthesis: no producer configured, cannot publish the synthesis event")
            return event
        synthesis_key = f"signal.synthesis.ready:{cluster_id}"
        await context.producer.emit(
            SignalSynthesisReady(
                id=occurrence_id(synthesis_key),
                subject=SignalSynthesisRef(str(cluster_id)),
                home=EventHomeMarker.NONE,
                data=SignalSynthesisReadyData(cluster_id=cluster_id, synthesis=artifact_dict),
                causationid=event.id,
            ),
            LegacyFacts(
                producer="signal-synthesize",
                level=EventLevel.WORKFLOW,
                domain="signal",
                visibility=EventVisibility.LOCAL,
                description=artifact.summary[:200],
                idempotency_key=synthesis_key,
            ),
        )
        return event
