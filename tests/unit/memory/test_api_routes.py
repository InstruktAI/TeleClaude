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

    async def test_delete_observation_returns_id_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeStore:
            async def delete_observation(self, _observation_id: int) -> bool:
                return True

        monkeypatch.setattr(api_routes, "MemoryStore", FakeStore)

        response = await api_routes.delete_observation(42)

        assert response == {"deleted": 42}


class TestTimelineRoute:
    async def test_timeline_delegates_to_search_and_serializes_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        timeline_calls: list[tuple[int, int, int, str | None]] = []

        class FakeSearch:
            async def timeline(
                self, anchor: int, depth_before: int, depth_after: int, project: str | None
            ) -> list[SearchResult]:
                timeline_calls.append((anchor, depth_before, depth_after, project))
                return [
                    SearchResult(
                        id=10,
                        title="Anchor observation",
                        subtitle=None,
                        type="discovery",
                        project="alpha",
                        narrative="Central event",
                        facts=None,
                        created_at="2025-01-01T00:00:00+00:00",
                        created_at_epoch=1735689600,
                    )
                ]

        monkeypatch.setattr(api_routes, "MemorySearch", FakeSearch)

        response = await api_routes.timeline(anchor=10, depth_before=2, depth_after=3, project="alpha")

        assert len(response) == 1
        assert response[0]["id"] == 10
        assert response[0]["title"] == "Anchor observation"
        assert response[0]["project"] == "alpha"
        assert timeline_calls == [(10, 2, 3, "alpha")]


class TestBatchFetchRoute:
    async def test_batch_fetch_delegates_to_search_and_serializes_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        batch_calls: list[tuple[list[int], str | None]] = []

        class FakeSearch:
            async def batch_fetch(self, ids: list[int], project: str | None) -> list[SearchResult]:
                batch_calls.append((ids, project))
                return [
                    SearchResult(
                        id=5,
                        title="Fetched observation",
                        subtitle=None,
                        type="gotcha",
                        project="beta",
                        narrative="Fetched content",
                        facts=["fact-a"],
                        created_at="2025-06-01T00:00:00+00:00",
                        created_at_epoch=1748736000,
                    )
                ]

        monkeypatch.setattr(api_routes, "MemorySearch", FakeSearch)

        response = await api_routes.batch_fetch(api_routes.BatchRequest(ids=[5, 6], project="beta"))

        assert len(response) == 1
        assert response[0]["id"] == 5
        assert response[0]["type"] == "gotcha"
        assert response[0]["facts"] == ["fact-a"]
        assert batch_calls == [([5, 6], "beta")]


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
