"""Shared transcript discovery helpers for history and mirror workflows."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from teleclaude.constants import AGENT_PROTOCOL
from teleclaude.core.agents import AgentName

__all__ = [
    "TranscriptCandidate",
    "build_source_identity",
    "discover_transcripts",
    "extract_project",
    "extract_session_id",
    "in_session_root",
]


@dataclass(frozen=True)
class TranscriptCandidate:
    """Discovered transcript file with metadata."""

    path: Path
    agent: AgentName
    mtime: float = 0.0


def _session_root(agent: AgentName) -> Path:
    return Path(str(AGENT_PROTOCOL[agent.value]["session_root"])).expanduser()


def _legacy_gemini_root() -> Path:
    """Legacy Gemini CLI transcript root, superseded by the Antigravity brain dir."""
    return Path(os.getenv("TELECLAUDE_LEGACY_GEMINI_ROOT", "~/.gemini/tmp")).expanduser()


def _session_roots(agent: AgentName) -> list[Path]:
    """All valid transcript roots for an agent, current layout first.

    Gemini/agy spans two layouts: the current Antigravity ``brain`` directory and
    the legacy ``~/.gemini/tmp`` tree. Both must be recognized so backward-compat
    paths keep a stable identity and are never treated as out-of-root.
    """
    roots = [_session_root(agent)]
    if agent == AgentName.GEMINI:
        roots.append(_legacy_gemini_root())
    return roots


def in_session_root(path: Path | str, agent: AgentName) -> bool:
    """Return whether a path lives under any of the agent's session roots."""
    expanded = Path(path).expanduser()
    for root in _session_roots(agent):
        try:
            expanded.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def build_source_identity(path: Path | str, agent: AgentName) -> str:
    """Build a deterministic identity from the transcript's path relative to its root.

    Resolves against each candidate root so legacy and current layouts produce the
    same identity they always had (no drift, no duplicate mirrors).
    """
    expanded_path = Path(path).expanduser()
    for root in _session_roots(agent):
        try:
            relative = expanded_path.relative_to(root)
            return f"{agent.value}:{relative.as_posix()}"
        except ValueError:
            continue
    return f"{agent.value}:{expanded_path.as_posix()}"


def discover_transcripts(agents: Sequence[AgentName] | None = None) -> list[TranscriptCandidate]:
    """Find transcript files for one or more agents, newest first."""
    candidates: list[TranscriptCandidate] = []
    for agent in agents or AgentName:
        root = _session_root(agent)

        # Glob primary path if it exists
        if root.exists():
            pattern = str(AGENT_PROTOCOL[agent.value]["session_pattern"])
            for path in root.glob(pattern):
                if path.is_file():
                    candidates.append(TranscriptCandidate(path=path, agent=agent, mtime=path.stat().st_mtime))

        # If agent is GEMINI, also search legacy fallback paths
        if agent == AgentName.GEMINI:
            legacy_root = _legacy_gemini_root()
            if legacy_root.exists():
                # Perform shallow, highly optimized globs to avoid blocking event loop recursive walks
                for pattern in ("*/chats/session-*.json", "session-*.json"):
                    for path in legacy_root.glob(pattern):
                        if path.is_file():
                            candidates.append(TranscriptCandidate(path=path, agent=agent, mtime=path.stat().st_mtime))

    candidates.sort(key=lambda c: c.mtime, reverse=True)
    return candidates


def extract_session_id(path: Path, agent: AgentName) -> str:
    """Derive a session identifier from an agent transcript path."""
    if agent == AgentName.CLAUDE:
        return path.stem
    if agent == AgentName.GEMINI:
        if path.suffix == ".jsonl":
            return path.parts[-4] if len(path.parts) >= 4 else path.stem
        return path.stem.replace("session-", "")
    if agent == AgentName.CODEX:
        return path.stem.split("_", 1)[0]
    return path.stem


def extract_project(path: Path, agent: AgentName) -> str:
    """Derive a project name from a transcript path."""
    if agent == AgentName.CLAUDE:
        mangled = path.parent.name
        parts = [part for part in mangled.split("-") if part]
        return parts[-1] if parts else ""
    if agent == AgentName.GEMINI:
        return "gemini"
    if agent == AgentName.CODEX:
        return "codex"
    return ""
