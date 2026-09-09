"""Owner-local transcript-chain discovery for session-scoping evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from teleclaude.core.agents import AgentName


@dataclass(frozen=True)
class TranscriptSource:
    """One chain member with the runtime that owns its parser."""

    path: str
    agent: AgentName
    native_session_id: str | None


_RUNTIME_ROOTS = {
    AgentName.CLAUDE: Path.home() / ".claude" / "projects",
    AgentName.CODEX: Path.home() / ".codex" / "sessions",
    AgentName.GEMINI: Path.home() / ".gemini" / "antigravity-cli" / "brain",
    AgentName.DEEPSEEK: Path.home() / ".dsh" / "sessions",
}


def resolve_transcript_sources(
    *,
    transcript_files: str | None,
    transcript_path: str | None,
    agent: AgentName,
    native_session_id: str | None,
) -> tuple[TranscriptSource, ...]:
    """Resolve the persisted chain plus the current transcript, or fail closed."""
    try:
        stored_paths = json.loads(transcript_files or "[]")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Session transcript chain is unreadable") from exc
    if not isinstance(stored_paths, list):
        raise ValueError("Session transcript chain is not a list")

    raw_paths = [str(path) for path in stored_paths if isinstance(path, str) and path]
    if transcript_path and transcript_path not in raw_paths:
        raw_paths.append(transcript_path)
    if not raw_paths:
        raise ValueError("Session transcript chain is empty")

    sources: list[TranscriptSource] = []
    for raw_path in raw_paths:
        path = Path(raw_path).expanduser()
        if not path.is_file():
            raise ValueError(f"Session transcript is unreadable: {path}")
        source_agent = _agent_for_path(path, fallback=agent)
        source_native_session_id = (
            native_session_id if source_agent is AgentName.CODEX and str(path) == transcript_path else None
        )
        sources.append(TranscriptSource(str(path), source_agent, source_native_session_id))
    return tuple(sources)


def _agent_for_path(path: Path, *, fallback: AgentName) -> AgentName:
    """Select the native parser from the registered runtime transcript roots."""
    resolved_path = path.resolve()
    for candidate, root in _RUNTIME_ROOTS.items():
        try:
            resolved_path.relative_to(root)
        except ValueError:
            continue
        return candidate
    return fallback
