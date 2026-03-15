from __future__ import annotations

import pytest

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

    def test_render_context_emits_observation_and_summary_sections(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(renderer_module.time, "time", lambda: 200)
        entries = [
            TimelineEntry(kind="observation", epoch=80, observation=_observation()),
            TimelineEntry(kind="summary", epoch=70, summary=_summary()),
        ]

        rendered = renderer_module.render_context(entries)
        lines = rendered.splitlines()

        assert lines[0] == "# Memory Context"
        assert any(line.startswith("## Recent Observations") for line in lines)
        assert any(line == "| 1 | discovery | Observation title | 2m ago |" for line in lines)
        assert any(line == "**Type:** discovery | **Concepts:** auth" for line in lines)
        assert any(line == "- fact-one" for line in lines)
        assert any(line == "## Session Summaries" for line in lines)
        assert any(line == "### Session: alpha" for line in lines)

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
