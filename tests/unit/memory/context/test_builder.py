from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy.sql.elements import TextClause

from teleclaude.core import db_models
from teleclaude.memory.context import builder as builder_module

pytestmark = pytest.mark.unit

RowValue = tuple[object, ...]


@dataclass
class FakeResult:
    rows: list[RowValue]

    def fetchall(self) -> list[RowValue]:
        return list(self.rows)


class FakeSyncSession:
    def __init__(self, outcomes: list[list[RowValue]]) -> None:
        self.outcomes = list(outcomes)
        self.statements: list[TextClause] = []

    def __enter__(self) -> FakeSyncSession:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def exec(self, statement: TextClause) -> FakeResult:
        if str(statement).startswith("PRAGMA"):
            return FakeResult([])
        self.statements.append(statement)
        return FakeResult(self.outcomes.pop(0))


def _observation(row_id: int, *, created_at_epoch: int = 100) -> db_models.MemoryObservation:
    return db_models.MemoryObservation(
        id=row_id,
        memory_session_id="session-1",
        project="alpha",
        type="discovery",
        title=f"Observation {row_id}",
        subtitle=None,
        facts='["fact"]',
        narrative="Narrative",
        concepts='["concept"]',
        files_read=None,
        files_modified=None,
        prompt_number=None,
        discovery_tokens=0,
        created_at="2025-01-01T00:00:00+00:00",
        created_at_epoch=created_at_epoch,
        identity_key=None,
    )


def _summary(row_id: int, *, created_at_epoch: int = 200) -> db_models.MemorySummary:
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
        created_at_epoch=created_at_epoch,
    )


def _observation_row(identity_key: str | None = None) -> RowValue:
    return (
        1,
        "session-1",
        "alpha",
        "discovery",
        "Observation 1",
        None,
        '["fact"]',
        "Narrative",
        '["concept"]',
        None,
        None,
        None,
        0,
        "2025-01-01T00:00:00+00:00",
        100,
        identity_key,
    )


class TestGenerateContext:
    async def test_generate_context_returns_empty_when_no_recent_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_get_recent_observations(
            project: str, limit: int = 50, identity_key: str | None = None
        ) -> list[db_models.MemoryObservation]:
            return []

        async def fake_get_recent_summaries(project: str, limit: int = 5) -> list[db_models.MemorySummary]:
            return []

        monkeypatch.setattr(builder_module, "_get_recent_observations", fake_get_recent_observations)
        monkeypatch.setattr(builder_module, "_get_recent_summaries", fake_get_recent_summaries)

        assert await builder_module.generate_context("alpha") == ""

    async def test_generate_context_passes_loaded_data_through_compile_filter_and_render(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        observations = [_observation(1)]
        summaries = [_summary(2)]
        compile_calls: list[tuple[list[db_models.MemoryObservation], list[db_models.MemorySummary]]] = []
        filter_calls: list[list[object]] = []
        render_calls: list[list[object]] = []

        async def fake_get_recent_observations(
            project: str, limit: int = 50, identity_key: str | None = None
        ) -> list[db_models.MemoryObservation]:
            return observations

        async def fake_get_recent_summaries(project: str, limit: int = 5) -> list[db_models.MemorySummary]:
            return summaries

        def fake_compile_timeline(
            loaded_observations: list[db_models.MemoryObservation],
            loaded_summaries: list[db_models.MemorySummary],
        ) -> list[object]:
            compile_calls.append((loaded_observations, loaded_summaries))
            return ["compiled"]

        def fake_filter_by_recency(entries: list[object], max_entries: int = 50) -> list[object]:
            filter_calls.append(entries)
            return ["filtered"]

        def fake_render_context(entries: list[object]) -> str:
            render_calls.append(entries)
            return "rendered"

        monkeypatch.setattr(builder_module, "_get_recent_observations", fake_get_recent_observations)
        monkeypatch.setattr(builder_module, "_get_recent_summaries", fake_get_recent_summaries)
        monkeypatch.setattr(builder_module, "compile_timeline", fake_compile_timeline)
        monkeypatch.setattr(builder_module, "filter_by_recency", fake_filter_by_recency)
        monkeypatch.setattr(builder_module, "render_context", fake_render_context)

        result = await builder_module.generate_context("alpha", identity_key="user-1")

        assert result == "rendered"
        assert compile_calls == [(observations, summaries)]
        assert filter_calls == [["compiled"]]
        assert render_calls == [["filtered"]]

    async def test_generate_context_returns_empty_when_recent_load_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def raise_recent_observations(
            project: str, limit: int = 50, identity_key: str | None = None
        ) -> list[db_models.MemoryObservation]:
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(builder_module, "_get_recent_observations", raise_recent_observations)

        assert await builder_module.generate_context("alpha") == ""

    def test_generate_context_sync_filters_observations_by_identity_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = FakeSyncSession([[_observation_row(identity_key="user-1")], []])

        monkeypatch.setattr(builder_module, "create_engine", lambda url: url)
        monkeypatch.setattr(builder_module, "SqlSession", lambda engine: session)
        monkeypatch.setattr(builder_module, "render_context", lambda entries: f"{len(entries)} entries")

        result = builder_module.generate_context_sync("alpha", "memory.sqlite", identity_key="user-1")

        assert result == "1 entries"
        assert session.statements[0].compile().params["identity_key"] == "user-1"
        assert session.statements[0].compile().params["project"] == "alpha"
        assert session.statements[1].compile().params["project"] == "alpha"
