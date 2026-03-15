from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from teleclaude.core.agents import AgentName
from teleclaude.mirrors import api_routes as api_routes_module
from teleclaude.mirrors.store import MirrorRecord, MirrorSearchResult

pytestmark = pytest.mark.unit


def _mirror_record(transcript_path: str) -> MirrorRecord:
    return MirrorRecord(
        session_id="session-1",
        source_identity="claude:alpha/session-1.jsonl",
        computer="mac",
        agent="claude",
        project="alpha",
        title="Mirror title",
        timestamp_start="2025-01-01T00:00:00+00:00",
        timestamp_end="2025-01-01T00:01:00+00:00",
        conversation_text="User: hi\n\nAssistant: hello",
        message_count=2,
        metadata={"transcript_path": transcript_path},
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:01:00+00:00",
    )


class TestParseAgentFilter:
    def test_parse_agent_filter_supports_all_and_csv_values(self) -> None:
        assert api_routes_module._parse_agent_filter("all") == list(AgentName)
        assert api_routes_module._parse_agent_filter(" claude , codex ") == [AgentName.CLAUDE, AgentName.CODEX]


class TestMirrorRoutes:
    async def test_search_mirror_routes_serializes_results_from_to_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        thread_calls: list[tuple[str, tuple[object, ...], int]] = []

        async def fake_to_thread(func: object, *args: object, **kwargs: object) -> list[MirrorSearchResult]:
            thread_calls.append((func.__name__, args, int(kwargs["limit"])))
            return [
                MirrorSearchResult(
                    session_id="session-1",
                    computer="mac",
                    agent="claude",
                    project="alpha",
                    title="Mirror title",
                    sort_timestamp="2025-01-01T00:00:00+00:00",
                    timestamp="Jan 1",
                    topic="topic",
                    conversation_text="User: hi",
                    metadata={"transcript_path": "/tmp/transcript.jsonl"},
                )
            ]

        monkeypatch.setattr(api_routes_module.asyncio, "to_thread", fake_to_thread)

        response = await api_routes_module.search_mirror_routes("index", agent="claude,codex", limit=5)

        assert response == [
            {
                "session_id": "session-1",
                "computer": "mac",
                "agent": "claude",
                "project": "alpha",
                "title": "Mirror title",
                "sort_timestamp": "2025-01-01T00:00:00+00:00",
                "timestamp": "Jan 1",
                "topic": "topic",
            }
        ]
        assert thread_calls == [("search_mirrors", ("index", [AgentName.CLAUDE, AgentName.CODEX]), 5)]

    async def test_search_mirror_routes_raises_400_for_unknown_agent(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await api_routes_module.search_mirror_routes("index", agent="unknown")

        assert exc_info.value.status_code == 400

    async def test_get_mirror_route_raises_404_when_no_mirror_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_to_thread(func: object, *args: object, **kwargs: object) -> None:
            return None

        monkeypatch.setattr(api_routes_module.asyncio, "to_thread", fake_to_thread)

        with pytest.raises(HTTPException) as exc_info:
            await api_routes_module.get_mirror_route("missing-session")

        assert exc_info.value.status_code == 404

    async def test_get_mirror_transcript_route_reads_the_transcript_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        transcript_path = tmp_path / "session.jsonl"
        transcript_path.write_text("User: hi\nAssistant: hello", encoding="utf-8")

        async def fake_to_thread(func: object, *args: object, **kwargs: object) -> MirrorRecord:
            return _mirror_record(str(transcript_path))

        monkeypatch.setattr(api_routes_module.asyncio, "to_thread", fake_to_thread)

        response = await api_routes_module.get_mirror_transcript_route("session-1")

        assert bytes(response.body).decode("utf-8") == "User: hi\nAssistant: hello"
