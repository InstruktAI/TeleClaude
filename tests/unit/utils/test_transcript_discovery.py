"""Characterization tests for teleclaude.utils.transcript_discovery."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import teleclaude.utils.transcript_discovery as transcript_discovery
from teleclaude.core.agents import AgentName

pytestmark = pytest.mark.unit


def _set_protocol_root(
    monkeypatch: pytest.MonkeyPatch,
    agent: AgentName,
    root: Path,
    pattern: str,
) -> None:
    monkeypatch.setitem(
        transcript_discovery.AGENT_PROTOCOL,
        agent.value,
        {
            **transcript_discovery.AGENT_PROTOCOL[agent.value],
            "session_root": str(root),
            "session_pattern": pattern,
        },
    )


class TestSessionRootHelpers:
    def test_in_session_root_and_source_identity_use_relative_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        root = tmp_path / "claude-root"
        transcript = root / "demo-project" / "session.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text("{}", encoding="utf-8")
        _set_protocol_root(monkeypatch, AgentName.CLAUDE, root, "*/*.jsonl")

        assert transcript_discovery.in_session_root(transcript, AgentName.CLAUDE) is True
        assert (
            transcript_discovery.build_source_identity(transcript, AgentName.CLAUDE)
            == "claude:demo-project/session.jsonl"
        )

    def test_build_source_identity_keeps_absolute_path_outside_session_root(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        root = tmp_path / "claude-root"
        outside = tmp_path / "outside.jsonl"
        outside.write_text("{}", encoding="utf-8")
        _set_protocol_root(monkeypatch, AgentName.CLAUDE, root, "*/*.jsonl")

        assert transcript_discovery.in_session_root(outside, AgentName.CLAUDE) is False
        assert transcript_discovery.build_source_identity(outside, AgentName.CLAUDE) == f"claude:{outside.as_posix()}"


class TestDiscoverTranscripts:
    def test_discovers_files_for_requested_agents_newest_first(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        claude_root = tmp_path / "claude"
        latest = claude_root / "beta" / "latest.jsonl"
        earliest = claude_root / "alpha" / "earliest.jsonl"
        latest.parent.mkdir(parents=True)
        earliest.parent.mkdir(parents=True)
        latest.write_text("{}", encoding="utf-8")
        earliest.write_text("{}", encoding="utf-8")
        os.utime(earliest, (100, 100))
        os.utime(latest, (200, 200))
        _set_protocol_root(monkeypatch, AgentName.CLAUDE, claude_root, "*/*.jsonl")
        _set_protocol_root(monkeypatch, AgentName.GEMINI, tmp_path / "missing-gemini", "*/chats/*.json")

        candidates = transcript_discovery.discover_transcripts([AgentName.CLAUDE, AgentName.GEMINI])

        assert [(candidate.path.name, candidate.agent, candidate.mtime) for candidate in candidates] == [
            ("latest.jsonl", AgentName.CLAUDE, 200.0),
            ("earliest.jsonl", AgentName.CLAUDE, 100.0),
        ]


class TestAgentSpecificMetadata:
    @pytest.mark.parametrize(
        ("agent", "path", "session_id", "project"),
        [
            (AgentName.CLAUDE, Path("/tmp/workspace-demo/session-123.jsonl"), "session-123", "demo"),
            (AgentName.GEMINI, Path("/tmp/run/chats/session-456.json"), "456", "gemini"),
            (AgentName.CODEX, Path("/tmp/2025/02/abc123_rollout.jsonl"), "abc123", "codex"),
        ],
    )
    def test_extract_session_id_and_project_follow_agent_rules(
        self,
        agent: AgentName,
        path: Path,
        session_id: str,
        project: str,
    ) -> None:
        assert transcript_discovery.extract_session_id(path, agent) == session_id
        assert transcript_discovery.extract_project(path, agent) == project
