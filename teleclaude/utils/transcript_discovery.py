"""Shared transcript discovery helpers for history and mirror workflows."""

from __future__ import annotations

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
    path: Path
    agent: AgentName
    mtime: float = 0.0


def _session_root(agent: AgentName) -> Path:
    return Path(str(AGENT_PROTOCOL[agent.value]["session_root"])).expanduser()


def in_session_root(path: Path | str, agent: AgentName) -> bool:
    """Return whether a path lives under the agent's session root."""
    try:
        Path(path).expanduser().relative_to(_session_root(agent))
        return True
    except ValueError:
        return False


def build_source_identity(path: Path | str, agent: AgentName) -> str:
    """Build a deterministic identity from the transcript's path relative to session_root."""
    expanded_path = Path(path).expanduser()
    root = _session_root(agent)
    try:
        relative = expanded_path.relative_to(root)
    except ValueError:
        relative = expanded_path
    return f"{agent.value}:{relative.as_posix()}"


def discover_transcripts(agents: Sequence[AgentName] | None = None) -> list[TranscriptCandidate]:
    """Find transcript files for one or more agents, newest first."""
    candidates: list[TranscriptCandidate] = []
    for agent in agents or AgentName:
        root = _session_root(agent)
        if not root.exists():
            continue
        pattern = str(AGENT_PROTOCOL[agent.value]["session_pattern"])
        for path in root.glob(pattern):
            if path.is_file():
                candidates.append(TranscriptCandidate(path=path, agent=agent, mtime=path.stat().st_mtime))
    candidates.sort(key=lambda c: c.mtime, reverse=True)
    return candidates


def extract_session_id(path: Path, agent: AgentName) -> str:
    """Derive a session identifier from an agent transcript path."""
    stem = path.stem
    if agent == AgentName.CLAUDE:
        return stem
    if agent == AgentName.GEMINI:
        return stem.replace("session-", "")
    if agent == AgentName.CODEX:
        return stem.split("_", 1)[0]
    return stem


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
