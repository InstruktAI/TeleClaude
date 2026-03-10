"""Unit tests for shared transcript discovery helpers."""

from __future__ import annotations

import os
from pathlib import Path

from teleclaude.constants import AGENT_PROTOCOL
from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript_discovery import (
    build_source_identity,
    discover_transcripts,
    extract_project,
    extract_session_id,
    is_canonical,
)


def test_discover_transcripts_uses_agent_specific_locations_and_sorts_newest_first(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    claude_session_dir = tmp_path / "claude" / "sessions"
    claude_project_dir = tmp_path / "claude" / "projects" / "team-history-search-upgrade"
    claude_subagent_dir = claude_project_dir / "subagents" / "worker"
    codex_session_dir = tmp_path / "codex" / "sessions"
    codex_legacy_dir = tmp_path / ".codex" / ".history" / "sessions"
    gemini_session_dir = tmp_path / "gemini" / "chats"

    for directory in (
        claude_session_dir,
        claude_project_dir,
        claude_subagent_dir,
        codex_session_dir,
        codex_legacy_dir,
        gemini_session_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CLAUDE.value], "session_dir", str(claude_session_dir))
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CLAUDE.value], "log_pattern", "*.jsonl")
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CODEX.value], "session_dir", str(codex_session_dir))
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CODEX.value], "log_pattern", "*.jsonl")
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.GEMINI.value], "session_dir", str(gemini_session_dir))
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.GEMINI.value], "log_pattern", "*.json")

    claude_path = claude_project_dir / "1234567890abcdef.jsonl"
    claude_path.write_text("{}\n", encoding="utf-8")
    os.utime(claude_path, (10, 10))

    claude_subagent_path = claude_subagent_dir / "fedcba0987654321.jsonl"
    claude_subagent_path.write_text("{}\n", encoding="utf-8")
    os.utime(claude_subagent_path, (30, 30))

    codex_path = codex_session_dir / "codex-123_more.jsonl"
    codex_path.write_text("{}\n", encoding="utf-8")
    os.utime(codex_path, (20, 20))

    codex_legacy_path = codex_legacy_dir / "codex-999_more.jsonl"
    codex_legacy_path.write_text("{}\n", encoding="utf-8")
    os.utime(codex_legacy_path, (40, 40))

    gemini_path = gemini_session_dir / "session-abcdef1234567890.json"
    gemini_path.write_text("{}\n", encoding="utf-8")
    os.utime(gemini_path, (15, 15))

    discovered = discover_transcripts([AgentName.CLAUDE, AgentName.CODEX, AgentName.GEMINI])

    assert [(candidate.path, candidate.agent) for candidate in discovered] == [
        (codex_path, AgentName.CODEX),
        (gemini_path, AgentName.GEMINI),
        (claude_path, AgentName.CLAUDE),
    ]
    assert claude_subagent_path not in [candidate.path for candidate in discovered]
    assert codex_legacy_path not in [candidate.path for candidate in discovered]


def test_is_canonical_enforces_agent_specific_allowlist(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    claude_path = tmp_path / "claude" / "projects" / "team" / "session.jsonl"
    claude_subagent_path = tmp_path / "claude" / "projects" / "team" / "subagents" / "worker" / "session.jsonl"
    codex_path = tmp_path / "codex" / "sessions" / "session.jsonl"
    codex_history_path = tmp_path / ".codex" / ".history" / "sessions" / "session.jsonl"
    gemini_path = tmp_path / "gemini" / "chats" / "session.json"

    assert is_canonical(claude_path, AgentName.CLAUDE) is True
    assert is_canonical(claude_subagent_path, AgentName.CLAUDE) is False
    assert is_canonical(codex_path, AgentName.CODEX) is True
    assert is_canonical(codex_history_path, AgentName.CODEX) is False
    assert is_canonical(gemini_path, AgentName.GEMINI) is True


def test_build_source_identity_prefers_canonical_relative_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    claude_session_dir = tmp_path / ".claude" / "sessions"
    claude_projects_dir = tmp_path / ".claude" / "projects"
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CLAUDE.value], "session_dir", str(claude_session_dir))

    project_path = claude_projects_dir / "teleclaude" / "session.jsonl"
    sessions_path = claude_session_dir / "abc123.jsonl"
    external_path = tmp_path / "exports" / "session.jsonl"

    assert build_source_identity(project_path, AgentName.CLAUDE) == "claude:teleclaude/session.jsonl"
    assert build_source_identity(sessions_path, AgentName.CLAUDE) == "claude:abc123.jsonl"
    assert build_source_identity(external_path, AgentName.CLAUDE) == f"claude:{external_path.as_posix()}"


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
