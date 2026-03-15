from __future__ import annotations

import pytest

from teleclaude.core import db_models
from teleclaude.memory.context.compiler import TimelineEntry, compile_timeline, filter_by_recency

pytestmark = pytest.mark.unit


def _observation(row_id: int, epoch: int) -> db_models.MemoryObservation:
    return db_models.MemoryObservation(
        id=row_id,
        memory_session_id="session-1",
        project="alpha",
        type="discovery",
        title=f"Observation {row_id}",
        subtitle=None,
        facts=None,
        narrative="Narrative",
        concepts=None,
        files_read=None,
        files_modified=None,
        prompt_number=None,
        discovery_tokens=0,
        created_at="2025-01-01T00:00:00+00:00",
        created_at_epoch=epoch,
        identity_key=None,
    )


def _summary(row_id: int, epoch: int) -> db_models.MemorySummary:
    return db_models.MemorySummary(
        id=row_id,
        memory_session_id="session-1",
        project="alpha",
        request="Request",
        investigated="Investigated",
        learned="Learned",
        completed="Completed",
        next_steps="Next",
        created_at="2025-01-01T00:00:00+00:00",
        created_at_epoch=epoch,
    )


class TestCompileTimeline:
    def test_compile_timeline_merges_entries_and_sorts_newest_first(self) -> None:
        entries = compile_timeline(
            observations=[_observation(1, 100), _observation(2, 300)],
            summaries=[_summary(3, 200)],
        )

        assert [entry.kind for entry in entries] == ["observation", "summary", "observation"]
        assert [entry.epoch for entry in entries] == [300, 200, 100]
        assert entries[0].observation is not None and entries[0].observation.id == 2
        assert entries[1].summary is not None and entries[1].summary.id == 3

    def test_filter_by_recency_returns_the_requested_prefix(self) -> None:
        entries = [
            TimelineEntry(kind="observation", epoch=300),
            TimelineEntry(kind="summary", epoch=200),
            TimelineEntry(kind="observation", epoch=100),
        ]

        assert filter_by_recency(entries, max_entries=2) == entries[:2]
