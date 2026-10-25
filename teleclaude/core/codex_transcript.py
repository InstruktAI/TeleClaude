"""Codex transcript discovery helpers.

Codex writes each thread — including every spawned subagent thread — to its OWN
``rollout-*-<thread_id>.jsonl`` file under ``~/.codex/sessions/YYYY/MM/DD/``. The
parent linkage lives only inside the file's first line
(``session_meta.payload.source.subagent.thread_spawn.parent_thread_id``).

This module owns:

- ``thread_id → transcript_path``, resolved from the rollout filename (used by
  ``todo_scaffold`` inside a Codex shell via ``$CODEX_THREAD_ID``, and wherever a
  session row lacks its transcript path).
- ``session_meta`` header parsing, which is how the receiver recognizes and drops
  subagent hook events.

Subagent transcripts are never read as evidence of the parent session's work; only
the session's own transcript is.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.agent_registry import AGENT_REGISTRY, AgentName

logger = get_logger(__name__)

_RECENT_DISCOVERY_DAYS = 7
_ROLLOUT_FILENAME_PATTERN = "rollout-*-{thread_id}.jsonl"
_SESSION_DATE_DIR_FORMAT = "%Y/%m/%d"
_THREAD_ID_ENV = AGENT_REGISTRY[AgentName.CODEX].native_session_id_env


class CodexInvocationMode(StrEnum):
    """How Codex recorded a transcript's invocation, from ``session_meta.payload.source``.

    ``source`` is a plain string for an ordinary invocation and a dict for a spawned
    subagent (``{"subagent": {"thread_spawn": {...}}}``); the dict shape carries no
    invocation mode and resolves to ``UNKNOWN`` here, since ``is_codex_subagent_transcript``
    already owns that case. ``UNKNOWN`` also covers a future value this enum does not yet
    name, so an unrecognized invocation is never silently treated as any known mode.
    """

    CLI = "cli"
    EXEC = "exec"
    VSCODE = "vscode"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HookTranscriptMetadata:
    """Normalized transcript metadata for a hook event."""

    transcript_path: str | None
    native_session_id: str | None
    native_log_file: str | None
    is_codex_subagent: bool


@dataclass(frozen=True)
class CodexTranscriptMeta:
    """Normalized Codex session_meta header for a transcript."""

    transcript_path: str
    thread_id: str | None
    parent_thread_id: str | None
    session_started_at: datetime | None
    cwd: str | None
    invocation_mode: CodexInvocationMode


class _CodexTranscriptIndex:
    """Process-local cache of Codex thread id to transcript path."""

    def __init__(self, sessions_dir: Path) -> None:
        self._sessions_dir = sessions_dir
        self._lock = threading.RLock()
        self._by_thread_id: dict[str, str] = {}

    def discover_path(self, native_session_id: str) -> str | None:
        """Resolve a thread's transcript path from its rollout filename."""
        if not native_session_id:
            return None
        with self._lock:
            cached = self._by_thread_id.get(native_session_id)
        if cached is not None:
            return cached
        path = self._scan_specific_thread(native_session_id)
        if path is not None:
            with self._lock:
                self._by_thread_id[native_session_id] = path
        return path

    def _scan_specific_thread(self, native_session_id: str) -> str | None:
        """Glob recent date directories first, then the whole tree, for the thread's rollout file."""
        pattern = _ROLLOUT_FILENAME_PATTERN.format(thread_id=native_session_id)
        today = datetime.now()
        for days_back in range(_RECENT_DISCOVERY_DAYS):
            date_dir = self._sessions_dir / (today - timedelta(days=days_back)).strftime(_SESSION_DATE_DIR_FORMAT)
            try:
                for transcript_file in date_dir.glob(pattern):
                    return str(transcript_file)
            except OSError:
                continue
        for transcript_file in self._sessions_dir.rglob(pattern):
            return str(transcript_file)
        return None


def _codex_sessions_dir() -> Path:
    """Return the Codex transcript root directory."""
    return Path.home() / ".codex" / "sessions"


@lru_cache(maxsize=4)
def _build_transcript_index(sessions_root: str) -> _CodexTranscriptIndex:
    """Build a transcript index for a specific sessions root."""
    return _CodexTranscriptIndex(Path(sessions_root))


def _get_transcript_index() -> _CodexTranscriptIndex:
    """Return the process-local transcript index for the current sessions root."""
    sessions_dir = _codex_sessions_dir()
    return _build_transcript_index(str(sessions_dir))


def _parse_codex_meta_timestamp(raw_timestamp: object) -> datetime | None:
    """Parse Codex session_meta timestamps into UTC-aware datetimes."""
    if not isinstance(raw_timestamp, str) or not raw_timestamp:
        return None

    normalized = f"{raw_timestamp[:-1]}+00:00" if raw_timestamp.endswith("Z") else raw_timestamp
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def read_codex_transcript_meta(transcript_path: str | Path | None) -> CodexTranscriptMeta | None:
    """Read Codex session metadata from the transcript header."""
    if not transcript_path:
        return None

    path = Path(transcript_path).expanduser()
    try:
        with path.open(encoding="utf-8") as handle:
            first_line = ""
            for line in handle:
                if line.strip():
                    first_line = line.strip()
                    break
        if not first_line:
            return None
        raw = json.loads(first_line)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(raw, dict) or raw.get("type") != "session_meta":
        return None
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        return None

    source = payload.get("source")
    subagent = source.get("subagent") if isinstance(source, dict) else None
    spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None

    try:
        invocation_mode = CodexInvocationMode(source) if isinstance(source, str) else CodexInvocationMode.UNKNOWN
    except ValueError:
        invocation_mode = CodexInvocationMode.UNKNOWN

    thread_id = payload.get("id")
    if not isinstance(thread_id, str) or not thread_id:
        thread_id = None

    parent_thread_id = spawn.get("parent_thread_id") if isinstance(spawn, dict) else None
    if not isinstance(parent_thread_id, str) or not parent_thread_id:
        parent_thread_id = None

    session_started_at = _parse_codex_meta_timestamp(raw.get("timestamp"))
    if session_started_at is None:
        session_started_at = _parse_codex_meta_timestamp(payload.get("timestamp"))

    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = None

    return CodexTranscriptMeta(
        transcript_path=str(path),
        thread_id=thread_id,
        parent_thread_id=parent_thread_id,
        session_started_at=session_started_at,
        cwd=cwd,
        invocation_mode=invocation_mode,
    )


def discover_codex_transcript_path(native_session_id: str) -> str | None:
    """Resolve Codex transcript path for a native session id.

    Codex stores transcripts in:
    ~/.codex/sessions/YYYY/MM/DD/rollout-*-{native_session_id}.jsonl
    """
    if not native_session_id:
        return None

    sessions_dir = _codex_sessions_dir()
    if not sessions_dir.exists():
        logger.debug(
            "Codex sessions directory not found",
            sessions_dir=str(sessions_dir),
        )
        return None

    path = _get_transcript_index().discover_path(native_session_id)
    if path:
        logger.debug(
            "Codex transcript discovered",
            native_session_id=native_session_id,
            path=path,
        )
        return path

    logger.debug("Codex transcript not found", native_session_id=native_session_id)
    return None


def discover_current_codex_transcript_path() -> str | None:
    """Resolve the current Codex parent transcript from the live shell environment."""
    if _THREAD_ID_ENV is None:
        return None
    current_thread_id = os.environ.get(_THREAD_ID_ENV, "").strip()  # fmt: skip  # guard: direct-env-read - allowed: bootstrap or internal process signal
    if not current_thread_id:
        return None
    return discover_codex_transcript_path(current_thread_id)


def is_codex_subagent_meta(meta: CodexTranscriptMeta | None) -> bool:
    """Return True when already-parsed transcript metadata belongs to a spawned Codex subagent.

    The single owner of the subagent determination: both the by-path convenience
    wrapper below and any caller that has already parsed the header (to avoid a second
    read when another rule needs the same metadata) resolve through this one check.
    """
    return bool(meta and meta.parent_thread_id)


def is_codex_subagent_transcript(transcript_path: str | None) -> bool:
    """Return True when the transcript belongs to a spawned Codex subagent."""
    return is_codex_subagent_meta(read_codex_transcript_meta(transcript_path))


def resolve_hook_transcript_metadata(
    *,
    session_id: str,
    event_type: str,
    data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
    normalized_agent_name: str,
) -> HookTranscriptMetadata:
    """Normalize hook transcript metadata and detect Codex subagents from provided transcript metadata only."""
    transcript_path = data.get("transcript_path")
    native_session_id = data.get("native_session_id")
    native_log_file = data.get("native_log_file")

    normalized_transcript_path = transcript_path if isinstance(transcript_path, str) and transcript_path else None
    normalized_native_session_id = (
        native_session_id if isinstance(native_session_id, str) and native_session_id else None
    )
    normalized_native_log_file = native_log_file if isinstance(native_log_file, str) and native_log_file else None

    is_codex_subagent = False
    if not normalized_transcript_path and normalized_native_log_file:
        normalized_transcript_path = normalized_native_log_file
        data["transcript_path"] = normalized_native_log_file

    if not is_codex_subagent and normalized_agent_name == "codex":
        candidate_path = normalized_transcript_path or normalized_native_log_file
        if candidate_path:
            is_codex_subagent = is_codex_subagent_transcript(candidate_path)

    return HookTranscriptMetadata(
        transcript_path=normalized_transcript_path,
        native_session_id=normalized_native_session_id,
        native_log_file=normalized_native_log_file,
        is_codex_subagent=is_codex_subagent,
    )
