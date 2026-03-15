"""Characterization tests for teleclaude.history.search."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from teleclaude.core.agents import AgentName
from teleclaude.history import search
from teleclaude.mirrors.store import MirrorRecord, MirrorSearchResult

pytestmark = pytest.mark.unit


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
            lambda query, agents, limit: [
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
        monkeypatch.setattr(search, "get_mirror", lambda session_id: mirror)

        search.show_transcript([AgentName.CLAUDE], "sess-1")

        output = capsys.readouterr().out
        assert "Demo Session" in output
        assert "Conversation body" in output


class TestParseAgents:
    def test_exits_for_unknown_agent_name(self) -> None:
        with pytest.raises(SystemExit):
            search.parse_agents("claude,unknown")
