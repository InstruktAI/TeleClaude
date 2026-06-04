from __future__ import annotations

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.core import db_models
from teleclaude.memory.context import renderer as renderer_module
from teleclaude.memory.context.compiler import TimelineEntry

pytestmark = pytest.mark.unit


def _observation(
    *,
    title: str = "Observation title",
    narrative: str = "Narrative text",
    facts: str | None = '["fact-one"]',
    concepts: str | None = '["auth"]',
    created_at_epoch: int = 80,
) -> db_models.MemoryObservation:
    return db_models.MemoryObservation(
        id=1,
        memory_session_id="session-1",
        project="alpha",
        type="discovery",
        title=title,
        subtitle=None,
        facts=facts,
        narrative=narrative,
        concepts=concepts,
        files_read=None,
        files_modified=None,
        prompt_number=None,
        discovery_tokens=0,
        created_at="2025-01-01T00:00:00+00:00",
        created_at_epoch=created_at_epoch,
        identity_key=None,
    )


def _summary() -> db_models.MemorySummary:
    return db_models.MemorySummary(
        id=2,
        memory_session_id="session-1",
        project="alpha",
        request="Request",
        investigated="Investigated",
        learned="Learned",
        completed="Completed",
        next_steps="Next",
        created_at="2025-01-01T00:00:00+00:00",
        created_at_epoch=70,
    )


class TestRenderContext:
    def test_render_context_returns_empty_string_for_no_entries(self) -> None:
        assert renderer_module.render_context([]) == ""

    def test_render_context_emits_observation_and_summary_sections(
        self, snapshot: SnapshotAssertion, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(renderer_module.time, "time", lambda: 200)
        entries = [
            TimelineEntry(kind="observation", epoch=80, observation=_observation()),
            TimelineEntry(kind="summary", epoch=70, summary=_summary()),
        ]

        rendered = renderer_module.render_context(entries)

        assert rendered == snapshot

    def test_render_context_index_under_top_n_uses_expanded_heading(
        self, snapshot: SnapshotAssertion, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(renderer_module.time, "time", lambda: 200)
        entries = [
            TimelineEntry(
                kind="observation", epoch=100 - i, observation=_observation(title=f"obs-{i}", created_at_epoch=100 - i)
            )
            for i in range(5)
        ]

        rendered = renderer_module.render_context(entries)
        lines = rendered.splitlines()
        detail_headings = [line for line in lines if line.startswith("### ")]

        assert rendered == snapshot
        assert len(detail_headings) == 5

    def test_render_context_index_at_or_above_top_n_uses_top_n_heading(
        self, snapshot: SnapshotAssertion, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(renderer_module.time, "time", lambda: 200)
        entries = [
            TimelineEntry(
                kind="observation", epoch=100 - i, observation=_observation(title=f"obs-{i}", created_at_epoch=100 - i)
            )
            for i in range(50)
        ]

        rendered = renderer_module.render_context(entries)
        lines = rendered.splitlines()
        detail_headings = [line for line in lines if line.startswith("### ")]
        index_rows = [line for line in lines if line.startswith("| ") and "obs-" in line]

        assert rendered == snapshot
        assert len(detail_headings) == renderer_module.MEMORY_EXPANDED_TOP_N
        assert len(index_rows) == 50

    def test_render_context_index_caps_at_one_hundred_when_total_exceeds(
        self, snapshot: SnapshotAssertion, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(renderer_module.time, "time", lambda: 200)
        entries = [
            TimelineEntry(
                kind="observation", epoch=200 - i, observation=_observation(title=f"obs-{i}", created_at_epoch=200 - i)
            )
            for i in range(150)
        ]

        rendered = renderer_module.render_context(entries)
        lines = rendered.splitlines()
        index_rows = [line for line in lines if line.startswith("| ") and "obs-" in line]
        detail_headings = [line for line in lines if line.startswith("### ")]

        assert rendered == snapshot
        assert len(index_rows) == renderer_module.MEMORY_INDEX_CAP
        assert len(detail_headings) == renderer_module.MEMORY_EXPANDED_TOP_N

    def test_render_context_ignores_invalid_json_fact_and_concept_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(renderer_module.time, "time", lambda: 200)
        entries = [
            TimelineEntry(
                kind="observation",
                epoch=80,
                observation=_observation(facts="not-json", concepts="not-json"),
            )
        ]

        rendered = renderer_module.render_context(entries)

        assert "Narrative text" in rendered
        assert "**Facts:**" not in rendered
        assert "**Concepts:**" not in rendered
