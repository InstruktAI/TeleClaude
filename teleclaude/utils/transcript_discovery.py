"""Shared transcript discovery helpers for history and mirror workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from teleclaude.constants import AGENT_PROTOCOL
from teleclaude.core.agents import AgentName


@dataclass(frozen=True)
class TranscriptCandidate:
    path: Path
    agent: AgentName
    mtime: float = 0.0


def discover_transcripts(agents: Sequence[AgentName] | None = None) -> list[TranscriptCandidate]:
    """Find transcript files for one or more agents, newest first."""
    requested_agents = tuple(agents or AgentName)
    candidates: list[TranscriptCandidate] = []
    seen: set[tuple[AgentName, Path]] = set()
    for agent in requested_agents:
        meta = AGENT_PROTOCOL[agent.value]
        session_dirs: list[Path] = [Path(str(meta["session_dir"])).expanduser()]
        if agent == AgentName.CLAUDE:
            projects_dir = session_dirs[0].parent / "projects"
            if projects_dir.exists():
                session_dirs = [projects_dir]
        if agent == AgentName.CODEX:
            session_dirs.append(Path("~/.codex/.history/sessions").expanduser())

        pattern = str(meta["log_pattern"])
        if pattern.startswith("**/"):
            pattern = pattern[3:]

        for session_dir in session_dirs:
            if not session_dir.exists():
                continue
            for path in session_dir.rglob(pattern):
                key = (agent, path)
                if not path.is_file() or key in seen:
                    continue
                candidates.append(TranscriptCandidate(path=path, agent=agent, mtime=path.stat().st_mtime))
                seen.add(key)
    candidates.sort(key=lambda candidate: candidate.mtime, reverse=True)
    return candidates


def extract_session_id(path: Path, agent: AgentName) -> str:
    """Derive a session identifier from an agent transcript path."""
    stem = path.stem
    if agent == AgentName.CLAUDE:
        return stem[:12]
    if agent == AgentName.GEMINI:
        return stem.replace("session-", "")[:12]
    if agent == AgentName.CODEX:
        return stem.split("_", 1)[0]
    return stem[:12]


def extract_project(path: Path, agent: AgentName) -> str:
    """Best-effort project fallback when the session context is unavailable."""
    if agent == AgentName.CLAUDE:
        mangled = path.parent.name
        parts = [part for part in mangled.split("-") if part]
        return parts[-1] if parts else ""
    if agent == AgentName.GEMINI:
        return "gemini"
    if agent == AgentName.CODEX:
        return "codex"
    return ""
