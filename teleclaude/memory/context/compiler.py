"""Compile observations and summaries into a unified timeline."""

from __future__ import annotations

from dataclasses import dataclass

from teleclaude.core import db_models


@dataclass
class TimelineEntry:
    """Unified entry for observations and summaries."""

    kind: str  # "observation" or "summary"
    epoch: int
    observation: db_models.MemoryObservation | None = None
    summary: db_models.MemorySummary | None = None


def compile_timeline(
    observations: list[db_models.MemoryObservation],
    summaries: list[db_models.MemorySummary],
) -> list[TimelineEntry]:
    """Merge observations and summaries into a chronological list (newest first)."""
    entries: list[TimelineEntry] = []

    for obs in observations:
        entries.append(TimelineEntry(kind="observation", epoch=obs.created_at_epoch, observation=obs))
    for summ in summaries:
        entries.append(TimelineEntry(kind="summary", epoch=summ.created_at_epoch, summary=summ))

    entries.sort(key=lambda e: e.epoch, reverse=True)
    return entries


def filter_by_recency(entries: list[TimelineEntry], max_entries: int = 50) -> list[TimelineEntry]:
    """Cap to most recent entries."""
    return entries[:max_entries]
