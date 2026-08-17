"""Shared transcript discovery helpers for history and mirror workflows."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from teleclaude.constants import AGENT_PROTOCOL
from teleclaude.core.agents import AgentName
from teleclaude.core.codex_transcript import discover_codex_transcript_path, read_codex_transcript_meta

__all__ = [
    "SessionId",
    "TranscriptCandidate",
    "build_source_identity",
    "discover_transcripts",
    "extract_project",
    "extract_session_id",
    "in_session_root",
    "recover_native_project",
]

_INVALID_SESSION_ID = "Session id must be a full UUID: {value}"
_MISSING_TRANSCRIPT_SESSION_ID = "Transcript does not carry a session id: {path}"
_CLAUDE_SUBAGENT_PREFIX = "agent-"
_GEMINI_SESSION_ID_FIELD = "sessionId"
_GEMINI_LEGACY_SESSION_PREFIX = "session-"
_JSONL_SUFFIX = ".jsonl"
_GIT_ENTRY = ".git"
_GITDIR_PREFIX = "gitdir:"
_GIT_COMMON_DIR_FILE = "commondir"
_UTF8 = "utf-8"
_EMPTY = ""


class SessionId(str):
    """Canonical full UUID used for transcript-derived session identity."""

    def __new__(cls, value: str) -> SessionId:
        try:
            parsed = UUID(value)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(_INVALID_SESSION_ID.format(value=value)) from exc
        canonical = str(parsed)
        if value.lower() != canonical:
            raise ValueError(_INVALID_SESSION_ID.format(value=value))
        return str.__new__(cls, canonical)


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


def extract_session_id(path: Path, agent: AgentName) -> SessionId | None:
    """Read a transcript's native session identifier from its authoritative source."""
    if agent == AgentName.CLAUDE:
        if path.stem.startswith(_CLAUDE_SUBAGENT_PREFIX):
            return None
        return SessionId(path.stem)
    if agent == AgentName.GEMINI:
        if path.suffix == _JSONL_SUFFIX and not path.name.startswith(_GEMINI_LEGACY_SESSION_PREFIX):
            return SessionId(path.parts[-4] if len(path.parts) >= 4 else path.stem)
        session_id = _read_gemini_legacy_session_id(path)
        if session_id is None:
            raise ValueError(_MISSING_TRANSCRIPT_SESSION_ID.format(path=path))
        return SessionId(session_id)
    if agent == AgentName.CODEX:
        metadata = read_codex_transcript_meta(path)
        if metadata is None or metadata.thread_id is None:
            raise ValueError(_MISSING_TRANSCRIPT_SESSION_ID.format(path=path))
        return SessionId(metadata.thread_id)
    return SessionId(path.stem)


def _read_gemini_legacy_session_id(path: Path) -> str | None:
    """Read the native session id from a legacy Gemini chat document."""
    try:
        if path.suffix == _JSONL_SUFFIX:
            with path.open(encoding=_UTF8) as handle:
                first_line = next((line for line in handle if line.strip()), _EMPTY)
            payload = json.loads(first_line)
        else:
            payload = json.loads(path.read_text(encoding=_UTF8))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get(_GEMINI_SESSION_ID_FIELD)
    return value if isinstance(value, str) and value else None


def extract_project(path: Path, agent: AgentName) -> str:
    """Derive the repository path from the transcript's recorded working directory."""
    if agent == AgentName.CLAUDE:
        working_dir = _read_claude_transcript_cwd(path)
        return _repository_project_from_working_dir(working_dir)
    if agent == AgentName.CODEX:
        metadata = read_codex_transcript_meta(path)
        working_dir = metadata.cwd if metadata is not None else None
        return _repository_project_from_working_dir(working_dir)
    return ""


def _repository_project_from_working_dir(working_dir: str | None) -> str:
    """Resolve a checkout to the repository that owns it, including git worktrees."""
    if not working_dir:
        return ""
    start = Path(working_dir).expanduser().resolve()
    candidates = (start, *start.parents)
    for candidate in candidates:
        git_entry = candidate / _GIT_ENTRY
        if git_entry.is_dir():
            return str(candidate)
        if not git_entry.is_file():
            continue
        try:
            declaration = git_entry.read_text(encoding=_UTF8).strip()
        except OSError:
            return str(candidate)
        if not declaration.startswith(_GITDIR_PREFIX):
            return str(candidate)
        git_dir = Path(declaration.removeprefix(_GITDIR_PREFIX).strip()).expanduser()
        if not git_dir.is_absolute():
            git_dir = (candidate / git_dir).resolve()
        common_dir_file = git_dir / _GIT_COMMON_DIR_FILE
        try:
            common_dir_value = common_dir_file.read_text(encoding=_UTF8).strip()
        except OSError:
            return str(candidate)
        common_dir = (git_dir / common_dir_value).resolve()
        return str(common_dir.parent) if common_dir.name == _GIT_ENTRY else str(candidate)
    return str(start)


def recover_native_project(
    native_session_id: str,
    agent: AgentName,
    caller_cwd: str | None,
) -> str | None:
    """Recover a native session's project directory from its own transcript.

    Each agent stores the project differently, so recovery dispatches per agent:
    Claude embeds a per-line ``cwd``; Codex records ``session_meta.payload.cwd``;
    Gemini stores no path and is confirmed only when ``sha256(caller_cwd)`` matches
    the legacy transcript's project-hash directory. Returns the recovered project
    path, or ``None`` when no source resolves — never the caller's directory as a
    blind default.
    """
    if not native_session_id:
        return None
    if agent == AgentName.CLAUDE:
        return _recover_claude_project(native_session_id)
    if agent == AgentName.CODEX:
        return _recover_codex_project(native_session_id)
    if agent == AgentName.GEMINI:
        return _recover_gemini_project(native_session_id, caller_cwd)
    return None


def _recover_claude_project(native_session_id: str) -> str | None:
    """Read the working directory embedded in the Claude transcript for a native id."""
    for candidate in discover_transcripts([AgentName.CLAUDE]):
        if extract_session_id(candidate.path, AgentName.CLAUDE) == native_session_id:
            return _read_claude_transcript_cwd(candidate.path)
    return None


def _read_claude_transcript_cwd(path: Path) -> str | None:
    """Return the first embedded ``cwd`` recorded in a Claude transcript, if any."""
    try:
        with Path(path).expanduser().open(encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    entry = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    cwd = entry.get("cwd")
                    if isinstance(cwd, str) and cwd:
                        return cwd
    except OSError:
        return None
    return None


def _recover_codex_project(native_session_id: str) -> str | None:
    """Read the working directory from the Codex rollout's session metadata."""
    path = discover_codex_transcript_path(native_session_id)
    if not path:
        return None
    meta = read_codex_transcript_meta(path)
    if meta is None:
        return None
    return meta.cwd


def _recover_gemini_project(native_session_id: str, caller_cwd: str | None) -> str | None:
    """Confirm the caller's directory against the legacy Gemini project hash.

    The Gemini transcript records no path. Legacy ``~/.gemini/tmp`` keys each chat
    by a directory named ``sha256(project_root)``, so the caller's invocation
    directory is admitted only when its hash matches that directory — a hash
    confirmation, not a blind fallback. Antigravity brain transcripts carry no
    such hash and therefore recover nothing here.
    """
    if not caller_cwd:
        return None
    project_hash = _locate_gemini_project_hash(native_session_id)
    if project_hash is None:
        return None
    candidate = str(Path(os.path.expanduser(os.path.expandvars(caller_cwd))).resolve())
    if hashlib.sha256(candidate.encode()).hexdigest() == project_hash:
        return candidate
    return None


def _locate_gemini_project_hash(native_session_id: str) -> str | None:
    """Return the legacy project-hash directory that stores a Gemini native id."""
    legacy_root = _legacy_gemini_root()
    for candidate in discover_transcripts([AgentName.GEMINI]):
        if extract_session_id(candidate.path, AgentName.GEMINI) != native_session_id:
            continue
        try:
            relative = candidate.path.expanduser().relative_to(legacy_root)
        except ValueError:
            continue
        if relative.parts:
            return relative.parts[0]
    return None
