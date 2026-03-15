from __future__ import annotations

import pytest
from fastapi import HTTPException

from teleclaude.memory import api_routes
from teleclaude.memory.types import ObservationInput, ObservationType, SearchResult

pytestmark = pytest.mark.unit


class TestSaveObservationRoute:
    async def test_save_observation_coerces_missing_lists_and_returns_store_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured_inputs: list[ObservationInput] = []

        class FakeStore:
            async def save_observation(self, inp: ObservationInput) -> object:
                captured_inputs.append(inp)
                return type("Result", (), {"id": 7, "title": "Saved", "project": "alpha"})()

        monkeypatch.setattr(api_routes, "MemoryStore", FakeStore)

        response = await api_routes.save_observation(
            api_routes.SaveObservationRequest(
                text="Remember this",
                project="alpha",
                type=ObservationType.GOTCHA,
                identity_key="user-1",
            )
        )

        assert response.model_dump() == {"id": 7, "title": "Saved", "project": "alpha"}
        saved_input = captured_inputs[0]
        assert saved_input.text == "Remember this"
        assert saved_input.project == "alpha"
        assert saved_input.type is ObservationType.GOTCHA
        assert saved_input.concepts == []
        assert saved_input.facts == []
        assert saved_input.identity_key == "user-1"


class TestSearchMemoryRoute:
    async def test_search_memory_passes_filters_and_serializes_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        search_calls: list[tuple[str, str | None, int, ObservationType | None, str | None]] = []

        class FakeSearch:
            async def search(
                self,
                query: str,
                project: str | None,
                limit: int,
                obs_type: ObservationType | None = None,
                identity_key: str | None = None,
            ) -> list[SearchResult]:
                search_calls.append((query, project, limit, obs_type, identity_key))
                return [
                    SearchResult(
                        id=4,
                        title="Cached auth gotcha",
                        subtitle=None,
                        type="gotcha",
                        project="alpha",
                        narrative="Cache invalidation matters",
                        facts=["invalidate", "retry"],
                        created_at="2025-01-01T00:00:00+00:00",
                        created_at_epoch=1735689600,
                    )
                ]

        monkeypatch.setattr(api_routes, "MemorySearch", FakeSearch)

        response = await api_routes.search_memory(
            query="cache",
            limit=3,
            project="alpha",
            type=ObservationType.GOTCHA,
            identity_key="user-1",
        )

        assert response == [
            {
                "id": 4,
                "title": "Cached auth gotcha",
                "subtitle": None,
                "type": "gotcha",
                "project": "alpha",
                "narrative": "Cache invalidation matters",
                "facts": ["invalidate", "retry"],
                "created_at": "2025-01-01T00:00:00+00:00",
                "created_at_epoch": 1735689600,
            }
        ]
        assert search_calls == [("cache", "alpha", 3, ObservationType.GOTCHA, "user-1")]


class TestDeleteObservationRoute:
    async def test_delete_observation_raises_404_when_store_reports_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeStore:
            async def delete_observation(self, observation_id: int) -> bool:
                assert observation_id == 99
                return False

        monkeypatch.setattr(api_routes, "MemoryStore", FakeStore)

        with pytest.raises(HTTPException) as exc_info:
            await api_routes.delete_observation(99)

        assert exc_info.value.status_code == 404


class TestInjectContextRoute:
    async def test_inject_context_uses_first_project_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        context_calls: list[tuple[str, str | None]] = []

        async def fake_generate_context(project: str, identity_key: str | None = None) -> str:
            context_calls.append((project, identity_key))
            return "context-body"

        monkeypatch.setattr(api_routes, "generate_context", fake_generate_context)

        response = await api_routes.inject_context(" alpha , beta ", identity_key="user-1")

        assert response == "context-body"
        assert context_calls == [("alpha", "user-1")]

    async def test_inject_context_returns_empty_string_for_blank_first_project(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fail_if_called(project: str, identity_key: str | None = None) -> str:
            raise AssertionError(f"generate_context should not run for {project=} {identity_key=}")

        monkeypatch.setattr(api_routes, "generate_context", fail_if_called)

        response = await api_routes.inject_context("   , beta")

        assert response == ""
