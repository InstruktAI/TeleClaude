# pyright: reportUnknownLambdaType=false
# pylint: disable=missing-function-docstring,missing-class-docstring,too-few-public-methods,unused-argument,protected-access,useless-return
"""Characterization tests for teleclaude.history.search."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict, cast

import pytest

from teleclaude.core.agents import AgentName
from teleclaude.history import search
from teleclaude.mirrors.store import MirrorRecord, MirrorSearchResult

pytestmark = pytest.mark.unit


class GetMirrorCall(TypedDict):
    session_id: str
    caller_email: str
    caller_role: str


class SearchMirrorsKwargs(TypedDict):
    limit: int
    caller_email: str
    caller_role: str


class SearchMirrorsCall(TypedDict):
    query: str
    kwargs: SearchMirrorsKwargs


class TestFindTranscript:
    def test_matches_session_id_prefix(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        transcript = tmp_path / "session-abc.txt"
        transcript.write_text("body", encoding="utf-8")
        candidates = [SimpleNamespace(path=transcript, agent=AgentName.CLAUDE)]
        monkeypatch.setattr(search, "discover_transcripts", lambda agents: candidates)
        monkeypatch.setattr(search, "extract_session_id", lambda path, agent: "abc123")

        match = search.find_transcript([AgentName.CLAUDE], "abc")

        assert match == (transcript, AgentName.CLAUDE)


class TestResolveRemoteComputerUrls:
    def test_returns_resolution_and_missing_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            search,
            "_fetch_local_daemon_computers",
            lambda: [{"name": "alpha", "host": "10.0.0.7"}, {"name": "local", "host": None}],
        )

        resolved, errors = search._resolve_remote_computer_urls(["alpha", "beta"])

        assert resolved["alpha"] == f"http://10.0.0.7:{search.API_TCP_PORT}"
        assert errors == {"beta": "Computer 'beta' not found in local daemon cache"}


class TestDisplayCombinedHistory:
    def test_prints_local_results(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(
            search,
            "search_mirrors",
            lambda query, agents, limit=20, **kwargs: [
                MirrorSearchResult(
                    session_id="sess-1",
                    computer="local",
                    agent="claude",
                    project="demo",
                    title="Title",
                    sort_timestamp="2024-01-01T00:00:00Z",
                    timestamp="2024-01-01 00:00",
                    topic="Topic",
                    conversation_text="body",
                    metadata={},
                )
            ],
        )

        search.display_combined_history([AgentName.CLAUDE], search_term="topic", limit=5)

        output = capsys.readouterr().out
        assert "sess-1" in output
        assert "Revive: telec sessions revive" in output


class TestShowTranscript:
    def test_prefers_local_mirror_for_non_raw_output(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mirror = MirrorRecord(
            session_id="sess-1",
            computer="laptop",
            agent="claude",
            project="demo",
            title="Demo Session",
            timestamp_start="2024-01-01T00:00:00Z",
            timestamp_end=None,
            conversation_text="Conversation body",
            message_count=1,
            metadata={},
            created_at="",
            updated_at="",
        )
        monkeypatch.setattr(search, "get_mirror", lambda session_id, **kwargs: mirror)

        search.show_transcript([AgentName.CLAUDE], "sess-1")

        output = capsys.readouterr().out
        assert "Demo Session" in output
        assert "Conversation body" in output

    @pytest.mark.timeout(5)
    def test_show_transcript_passes_caller_context_to_get_mirror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: GetMirrorCall = {"session_id": "", "caller_email": "", "caller_role": ""}

        def fake_get_mirror(session_id: str, **kwargs: object) -> MirrorRecord | None:
            captured["session_id"] = session_id
            captured["caller_email"] = cast(str, kwargs["caller_email"])
            captured["caller_role"] = cast(str, kwargs["caller_role"])
            return None

        monkeypatch.setattr(search, "get_mirror", fake_get_mirror)

        with pytest.raises(SystemExit):
            cast(Any, search.show_transcript)(
                [AgentName.CLAUDE],
                "sess-1",
                caller_email="member@example.com",
                caller_role="member",
            )

        assert captured["session_id"] == "sess-1"
        assert captured["caller_email"] == "member@example.com"
        assert captured["caller_role"] == "member"


class TestRoleAwareHistorySpecs:
    def test_display_combined_history_passes_caller_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: SearchMirrorsCall = {
            "query": "",
            "kwargs": {"limit": 0, "caller_email": "", "caller_role": ""},
        }

        def fake_search_mirrors(query: str, agents: list[AgentName], **kwargs: object) -> list[MirrorSearchResult]:
            captured["query"] = query
            captured["kwargs"] = {
                "limit": cast(int, kwargs["limit"]),
                "caller_email": cast(str, kwargs["caller_email"]),
                "caller_role": cast(str, kwargs["caller_role"]),
            }
            return []

        monkeypatch.setattr(search, "search_mirrors", fake_search_mirrors)

        cast(Any, search.display_combined_history)(
            [AgentName.CLAUDE],
            search_term="topic",
            limit=5,
            caller_email="member@example.com",
            caller_role="member",
        )

        assert captured["query"] == "topic"
        assert captured["kwargs"] == {"limit": 5, "caller_email": "member@example.com", "caller_role": "member"}


class TestParseAgents:
    def test_exits_for_unknown_agent_name(self) -> None:
        with pytest.raises(SystemExit):
            search.parse_agents("claude,unknown")
