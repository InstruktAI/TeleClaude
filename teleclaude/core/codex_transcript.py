"""Codex transcript discovery helpers.

Core-owned utility for resolving Codex native transcript paths.
"""

from __future__ import annotations

import json
import os
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


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


def _codex_sessions_dir() -> Path:
    """Return the Codex transcript root directory."""
    return Path.home() / ".codex" / "sessions"


def _iter_codex_transcript_paths(sessions_dir: Path) -> Iterator[Path]:
    """Yield every Codex transcript path under the sessions directory."""
    if not sessions_dir.exists():
        return
    yield from sessions_dir.rglob("rollout-*.jsonl")


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
            first_line = handle.readline().strip()
        raw = json.loads(first_line)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(raw, dict):
        return None
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        return None

    source = payload.get("source")
    subagent = source.get("subagent") if isinstance(source, dict) else None
    spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None

    thread_id = payload.get("id")
    if not isinstance(thread_id, str) or not thread_id:
        thread_id = None

    parent_thread_id = spawn.get("parent_thread_id") if isinstance(spawn, dict) else None
    if not isinstance(parent_thread_id, str) or not parent_thread_id:
        parent_thread_id = None

    session_started_at = _parse_codex_meta_timestamp(raw.get("timestamp"))
    if session_started_at is None:
        session_started_at = _parse_codex_meta_timestamp(payload.get("timestamp"))

    return CodexTranscriptMeta(
        transcript_path=str(path),
        thread_id=thread_id,
        parent_thread_id=parent_thread_id,
        session_started_at=session_started_at,
    )


def _discover_codex_children_by_parent(sessions_dir: Path) -> dict[str, list[CodexTranscriptMeta]]:
    """Index Codex child transcripts by parent thread id."""
    children_by_parent: dict[str, list[CodexTranscriptMeta]] = {}

    for transcript_file in _iter_codex_transcript_paths(sessions_dir):
        meta = read_codex_transcript_meta(transcript_file)
        if meta is None or not meta.parent_thread_id:
            continue
        children_by_parent.setdefault(meta.parent_thread_id, []).append(meta)

    for children in children_by_parent.values():
        children.sort(
            key=lambda meta: (
                meta.session_started_at is None,
                meta.session_started_at.isoformat() if meta.session_started_at else "",
                meta.transcript_path,
            )
        )

    return children_by_parent


def discover_codex_transcript_family_meta(
    *,
    root_transcript_path: str | None = None,
    root_thread_id: str | None = None,
) -> list[CodexTranscriptMeta]:
    """Resolve parent and descendant Codex transcript metadata recursively."""
    family_meta: list[CodexTranscriptMeta] = []
    seen_paths: set[str] = set()

    def append_meta(meta: CodexTranscriptMeta | None) -> None:
        if meta is None or meta.transcript_path in seen_paths:
            return
        family_meta.append(meta)
        seen_paths.add(meta.transcript_path)

    root_meta_from_path = read_codex_transcript_meta(root_transcript_path)
    fallback_root_meta = None
    if root_meta_from_path is None and root_transcript_path:
        fallback_root_meta = CodexTranscriptMeta(
            transcript_path=str(Path(root_transcript_path).expanduser()),
            thread_id=None,
            parent_thread_id=None,
            session_started_at=None,
        )
    elif root_meta_from_path is not None:
        fallback_root_meta = root_meta_from_path

    resolved_root_thread_id = root_thread_id or (
        root_meta_from_path.thread_id if root_meta_from_path and root_meta_from_path.thread_id else None
    )
    if not resolved_root_thread_id:
        append_meta(fallback_root_meta)
        return family_meta

    append_meta(read_codex_transcript_meta(discover_codex_transcript_path(resolved_root_thread_id)))
    append_meta(fallback_root_meta)

    sessions_dir = _codex_sessions_dir()
    if not sessions_dir.exists():
        return family_meta

    children_by_parent = _discover_codex_children_by_parent(sessions_dir)
    seen_threads: set[str] = set()
    pending: deque[str] = deque([resolved_root_thread_id])

    while pending:
        parent_thread_id = pending.popleft()
        if parent_thread_id in seen_threads:
            continue
        seen_threads.add(parent_thread_id)

        for child_meta in children_by_parent.get(parent_thread_id, []):
            append_meta(child_meta)
            if child_meta.thread_id and child_meta.thread_id not in seen_threads:
                pending.append(child_meta.thread_id)

    return family_meta


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

    today = datetime.now()
    for days_back in range(7):
        try:
            check_date = today - timedelta(days=days_back)
            date_dir = sessions_dir / f"{check_date.year}" / f"{check_date.month:02d}" / f"{check_date.day:02d}"
            if not date_dir.exists():
                continue
            for transcript_file in date_dir.glob(f"rollout-*-{native_session_id}.jsonl"):
                logger.debug(
                    "Codex transcript discovered",
                    native_session_id=native_session_id,
                    path=str(transcript_file),
                )
                return str(transcript_file)
        except (ValueError, OSError) as exc:
            logger.debug(
                "Codex transcript date scan error",
                days_back=days_back,
                error=str(exc),
            )

    logger.debug("Falling back to recursive Codex transcript search", native_session_id=native_session_id)
    for transcript_file in sessions_dir.rglob(f"rollout-*-{native_session_id}.jsonl"):
        logger.debug(
            "Codex transcript discovered (recursive)",
            native_session_id=native_session_id,
            path=str(transcript_file),
        )
        return str(transcript_file)

    logger.warning("Codex transcript not found", native_session_id=native_session_id)
    return None


def discover_current_codex_transcript_path() -> str | None:
    """Resolve the current Codex parent transcript from the live shell environment."""
    current_thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    if not current_thread_id:
        return None
    return discover_codex_transcript_path(current_thread_id)


def discover_codex_transcript_family(
    *,
    root_transcript_path: str | None = None,
    root_thread_id: str | None = None,
) -> list[str]:
    """Resolve the parent transcript plus every descendant Codex subagent transcript."""
    return [
        meta.transcript_path
        for meta in discover_codex_transcript_family_meta(
            root_transcript_path=root_transcript_path,
            root_thread_id=root_thread_id,
        )
    ]


def is_codex_subagent_transcript(transcript_path: str | None) -> bool:
    """Return True when the transcript belongs to a spawned Codex subagent."""
    meta = read_codex_transcript_meta(transcript_path)
    return bool(meta and meta.parent_thread_id)


def should_persist_codex_native_metadata(
    *,
    native_log_file: str | None,
    native_session_id: str | None,
) -> bool:
    """Keep parent-session native metadata stable only when the provided transcript proves subagent."""
    del native_session_id
    transcript_path = native_log_file
    if not transcript_path:
        return True
    return not is_codex_subagent_transcript(transcript_path)


def resolve_hook_transcript_metadata(
    *,
    session_id: str,  # pylint: disable=unused-argument
    event_type: str,  # pylint: disable=unused-argument
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
