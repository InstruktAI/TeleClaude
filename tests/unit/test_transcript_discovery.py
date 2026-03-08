"""Unit tests for shared transcript discovery helpers."""

from __future__ import annotations

import os
from pathlib import Path

from teleclaude.constants import AGENT_PROTOCOL
from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript_discovery import discover_transcripts, extract_project, extract_session_id


def test_discover_transcripts_uses_agent_specific_locations_and_sorts_newest_first(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    claude_session_dir = tmp_path / "claude" / "sessions"
    claude_project_dir = tmp_path / "claude" / "projects" / "team-history-search-upgrade"
    codex_session_dir = tmp_path / "codex" / "sessions"
    codex_legacy_dir = tmp_path / ".codex" / ".history" / "sessions"

    for directory in (claude_session_dir, claude_project_dir, codex_session_dir, codex_legacy_dir):
        directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CLAUDE.value], "session_dir", str(claude_session_dir))
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CLAUDE.value], "log_pattern", "*.jsonl")
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CODEX.value], "session_dir", str(codex_session_dir))
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CODEX.value], "log_pattern", "*.jsonl")

    claude_path = claude_project_dir / "1234567890abcdef.jsonl"
    claude_path.write_text("{}\n", encoding="utf-8")
    os.utime(claude_path, (10, 10))

    codex_path = codex_legacy_dir / "codex-123_more.jsonl"
    codex_path.write_text("{}\n", encoding="utf-8")
    os.utime(codex_path, (20, 20))

    discovered = discover_transcripts([AgentName.CLAUDE, AgentName.CODEX])

    assert [(candidate.path, candidate.agent) for candidate in discovered] == [
        (codex_path, AgentName.CODEX),
        (claude_path, AgentName.CLAUDE),
    ]


def test_extract_session_id_and_project_follow_agent_rules() -> None:
    claude_path = Path("/tmp/projects/team-history-search-upgrade/1234567890abcdef.jsonl")
    gemini_path = Path("/tmp/chats/session-abcdef1234567890.json")
    codex_path = Path("/tmp/codex/codex-123_more.jsonl")

    assert extract_session_id(claude_path, AgentName.CLAUDE) == "1234567890ab"
    assert extract_session_id(gemini_path, AgentName.GEMINI) == "abcdef123456"
    assert extract_session_id(codex_path, AgentName.CODEX) == "codex-123"

    assert extract_project(claude_path, AgentName.CLAUDE) == "upgrade"
    assert extract_project(gemini_path, AgentName.GEMINI) == "gemini"
    assert extract_project(codex_path, AgentName.CODEX) == "codex"
