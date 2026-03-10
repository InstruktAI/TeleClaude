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
    in_session_root,
)


def test_discover_transcripts_uses_agent_specific_locations_and_sorts_newest_first(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    # Claude: session_root/project-dir/*.jsonl
    claude_root = tmp_path / ".claude" / "projects"
    claude_path = claude_root / "team-history" / "1234567890abcdef.jsonl"
    claude_subagent_path = claude_root / "team-history" / "subagents" / "worker" / "fedcba.jsonl"

    # Codex: session_root/year/month/day/*.jsonl
    codex_root = tmp_path / ".codex" / "sessions"
    codex_path = codex_root / "2026" / "03" / "10" / "rollout-abc.jsonl"

    # Gemini: session_root/hash/chats/*.json
    gemini_root = tmp_path / ".gemini" / "tmp"
    gemini_path = gemini_root / "abc123hash" / "chats" / "session-abcdef.json"
    gemini_logs = gemini_root / "abc123hash" / "logs.json"  # must not be discovered

    for path in (claude_path, claude_subagent_path, codex_path, gemini_path, gemini_logs):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    os.utime(claude_path, (10, 10))
    os.utime(claude_subagent_path, (30, 30))
    os.utime(codex_path, (20, 20))
    os.utime(gemini_path, (15, 15))

    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CLAUDE.value], "session_root", str(claude_root))
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CLAUDE.value], "session_pattern", "*/*.jsonl")
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CODEX.value], "session_root", str(codex_root))
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CODEX.value], "session_pattern", "**/*.jsonl")
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.GEMINI.value], "session_root", str(gemini_root))
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.GEMINI.value], "session_pattern", "*/chats/*.json")

    discovered = discover_transcripts([AgentName.CLAUDE, AgentName.CODEX, AgentName.GEMINI])
    paths = [c.path for c in discovered]

    assert codex_path in paths
    assert gemini_path in paths
    assert claude_path in paths
    assert claude_subagent_path not in paths  # excluded by pattern depth
    assert gemini_logs not in paths  # excluded by pattern
    assert [(c.path, c.agent) for c in discovered] == sorted(
        [(c.path, c.agent) for c in discovered], key=lambda x: -next(c.mtime for c in discovered if c.path == x[0])
    )


def test_in_session_root_matches_paths_under_session_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    claude_root = tmp_path / ".claude" / "projects"
    codex_root = tmp_path / ".codex" / "sessions"
    gemini_root = tmp_path / ".gemini" / "tmp"

    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CLAUDE.value], "session_root", str(claude_root))
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CODEX.value], "session_root", str(codex_root))
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.GEMINI.value], "session_root", str(gemini_root))

    assert in_session_root(claude_root / "proj" / "session.jsonl", AgentName.CLAUDE) is True
    assert in_session_root(tmp_path / "elsewhere" / "session.jsonl", AgentName.CLAUDE) is False
    assert in_session_root(codex_root / "2026" / "03" / "session.jsonl", AgentName.CODEX) is True
    assert in_session_root(gemini_root / "hash" / "chats" / "session.json", AgentName.GEMINI) is True


def test_build_source_identity_is_relative_to_session_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    claude_root = tmp_path / ".claude" / "projects"
    monkeypatch.setitem(AGENT_PROTOCOL[AgentName.CLAUDE.value], "session_root", str(claude_root))

    path_inside = claude_root / "teleclaude" / "session.jsonl"
    path_outside = tmp_path / "exports" / "session.jsonl"

    assert build_source_identity(path_inside, AgentName.CLAUDE) == "claude:teleclaude/session.jsonl"
    assert build_source_identity(path_outside, AgentName.CLAUDE) == f"claude:{path_outside.as_posix()}"


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
