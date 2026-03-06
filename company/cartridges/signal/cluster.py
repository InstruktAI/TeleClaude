"""Signal cluster cartridge — groups ingested items and emits signal.cluster.formed."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from teleclaude_events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude_events.signal.ai import SignalAIClient
from teleclaude_events.signal.clustering import (
    ClusteringConfig,
    build_cluster_key,
    detect_burst,
    detect_novelty,
    group_by_tags,
    refine_by_embeddings,
)
from teleclaude_events.signal.db import SignalDB

if TYPE_CHECKING:
    from teleclaude_events.pipeline import PipelineContext

logger = logging.getLogger(__name__)


class SignalClusterCartridge:
    name = "signal-cluster"

    def __init__(self, config: ClusteringConfig, ai: SignalAIClient, signal_db: SignalDB) -> None:
        self._config = config
        self._ai = ai
        self._signal_db = signal_db

    async def process(self, event: EventEnvelope, context: "PipelineContext") -> EventEnvelope | None:
        if event.event != "signal.ingest.received":
            return event
        # Run a clustering pass after each ingested item (the pass is idempotent).
        await self.cluster_pass(context)
        return event

    async def cluster_pass(self, context: "PipelineContext") -> int:
        """Explicit cluster pass — returns count of clusters formed."""
        window_start = datetime.now(timezone.utc) - timedelta(seconds=self._config.window_seconds)
        items = await self._signal_db.get_unclustered_items(since=window_start)

        if not items:
            return 0

        # Tag-based grouping
        tag_groups = group_by_tags(items, min_overlap=self._config.tag_overlap_min)

        # Refine each group by embeddings
        refined: list[list[dict[str, object]]] = []
        for group in tag_groups:
            refined.extend(refine_by_embeddings(group, self._config.embedding_similarity_threshold))

        recent_tags = await self._signal_db.get_recent_cluster_tags(hours=self._config.novelty_overlap_hours)
        clusters_formed = 0

        for group in refined:
            if len(group) < self._config.min_cluster_size:
                continue

            member_ids = [int(item["id"]) for item in group if item.get("id")]  # type: ignore[arg-type]
            ikeys = [str(item.get("idempotency_key", "")) for item in group]
            cluster_key = build_cluster_key(ikeys)

            all_tags: list[str] = []
            for item in group:
                all_tags.extend(item.get("tags", []))  # type: ignore[arg-type]
            unique_tags = list(dict.fromkeys(all_tags))

            is_burst = detect_burst(group, self._config.burst_threshold)
            is_novel = detect_novelty(unique_tags, recent_tags)

            # AI-generate cluster summary
            titles = [str(item.get("raw_title", "")) for item in group[:5]]
            summary_prompt = "; ".join(t for t in titles if t)
            try:
                summary = await self._ai.summarise(summary_prompt, "")
            except Exception as e:
                logger.warning(
                    "Cluster summary generation failed for group of %d items: %s; skipping cluster this pass",
                    len(group),
                    e,
                )
                continue

            cluster_id = await self._signal_db.insert_cluster(
                cluster_key=cluster_key,
                tags=unique_tags,
                is_burst=is_burst,
                is_novel=is_novel,
                summary=summary,
                member_ids=member_ids,
            )
            if cluster_id == 0:
                # Cluster already exists (idempotency via cluster_key UNIQUE)
                continue

            await self._signal_db.assign_items_to_cluster(member_ids, cluster_id)

            envelope = EventEnvelope(
                event="signal.cluster.formed",
                source="signal-cluster",
                level=EventLevel.OPERATIONAL,
                domain="signal",
                visibility=EventVisibility.LOCAL,
                description=summary,
                idempotency_key=f"signal.cluster.formed:{cluster_key}",
                payload={
                    "cluster_id": cluster_id,
                    "member_count": len(group),
                    "tags": unique_tags,
                    "is_burst": is_burst,
                    "is_novel": is_novel,
                    "summary": summary,
                },
            )
            if context.emit:
                await context.emit(envelope)
            clusters_formed += 1

        return clusters_formed
