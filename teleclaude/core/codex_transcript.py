"""Codex transcript discovery helpers.

Core-owned utility for resolving Codex native transcript paths.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import deque
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_RECENT_DISCOVERY_DAYS = 7
_ROLLOUT_FILENAME_RE = re.compile(
    r"^rollout-(?P<stamp>.+)-"
    r"(?P<native_session_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$"
)


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


@dataclass(frozen=True)
class CodexRecentTranscriptCandidate:
    """Candidate transcript discovered before native metadata is bound."""

    transcript_path: str
    native_session_id: str


class _CodexTranscriptIndex:  # pylint: disable=too-many-instance-attributes
    """Process-local transcript index for fast family/path resolution."""

    def __init__(self, sessions_dir: Path) -> None:
        self._sessions_dir = sessions_dir
        self._lock = threading.RLock()
        self._bootstrapped = False
        self._by_path: dict[str, CodexTranscriptMeta] = {}
        self._by_thread_id: dict[str, CodexTranscriptMeta] = {}
        self._children_by_parent: dict[str, list[CodexTranscriptMeta]] = {}
        self._known_paths: set[str] = set()
        self._dir_known_files: dict[str, set[str]] = {}

    def discover_path(self, native_session_id: str) -> str | None:
        """Resolve transcript path from indexed metadata."""
        if not native_session_id:
            return None
        self._ensure_bootstrapped()
        self._refresh_recent()
        with self._lock:
            meta = self._by_thread_id.get(native_session_id)
            if meta is not None:
                return meta.transcript_path
        return self._scan_specific_thread(native_session_id)

    def discover_family_meta(
        self,
        *,
        root_transcript_path: str | None = None,
        root_thread_id: str | None = None,
    ) -> list[CodexTranscriptMeta]:
        """Resolve parent and descendants from indexed transcript metadata."""
        self._ensure_bootstrapped()
        if root_transcript_path:
            self._index_path(Path(root_transcript_path).expanduser())
        self._refresh_recent()

        family_meta: list[CodexTranscriptMeta] = []
        seen_paths: set[str] = set()

        def append_meta(meta: CodexTranscriptMeta | None) -> None:
            if meta is None or meta.transcript_path in seen_paths:
                return
            family_meta.append(meta)
            seen_paths.add(meta.transcript_path)

        fallback_root_meta = None
        root_meta_from_path = read_codex_transcript_meta(root_transcript_path)
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

        root_path = self.discover_path(resolved_root_thread_id)
        append_meta(read_codex_transcript_meta(root_path))
        append_meta(fallback_root_meta)

        with self._lock:
            seen_threads: set[str] = set()
            pending: deque[str] = deque([resolved_root_thread_id])

            while pending:
                parent_thread_id = pending.popleft()
                if parent_thread_id in seen_threads:
                    continue
                seen_threads.add(parent_thread_id)

                for child_meta in self._children_by_parent.get(parent_thread_id, []):
                    append_meta(child_meta)
                    if child_meta.thread_id and child_meta.thread_id not in seen_threads:
                        pending.append(child_meta.thread_id)

        return family_meta

    def _ensure_bootstrapped(self) -> None:
        with self._lock:
            if self._bootstrapped:
                return
        self._scan_all()
        with self._lock:
            self._bootstrapped = True

    def _scan_all(self) -> None:
        sessions_dir = self._sessions_dir
        if not sessions_dir.exists():
            return
        for transcript_file in _iter_codex_transcript_paths(sessions_dir):
            self._index_path(transcript_file)

    def _refresh_recent(self) -> None:
        sessions_dir = self._sessions_dir
        if not sessions_dir.exists():
            return

        today = datetime.now()
        for days_back in range(_RECENT_DISCOVERY_DAYS):
            try:
                check_date = today - timedelta(days=days_back)
                date_dir = sessions_dir / f"{check_date.year}" / f"{check_date.month:02d}" / f"{check_date.day:02d}"
            except ValueError:
                continue
            self._refresh_directory(date_dir)

    def _refresh_directory(self, date_dir: Path) -> None:
        if not date_dir.exists():
            return
        try:
            current_files = {str(path) for path in date_dir.glob("rollout-*.jsonl") if path.is_file()}
        except OSError:
            return

        dir_key = str(date_dir)
        with self._lock:
            known_files = self._dir_known_files.get(dir_key, set())
            new_files = current_files - known_files
            self._dir_known_files[dir_key] = current_files

        for file_path in sorted(new_files):
            self._index_path(Path(file_path))

    def _scan_specific_thread(self, native_session_id: str) -> str | None:
        sessions_dir = self._sessions_dir
        if not sessions_dir.exists():
            return None

        today = datetime.now()
        for days_back in range(_RECENT_DISCOVERY_DAYS):
            try:
                check_date = today - timedelta(days=days_back)
                date_dir = sessions_dir / f"{check_date.year}" / f"{check_date.month:02d}" / f"{check_date.day:02d}"
                if not date_dir.exists():
                    continue
                for transcript_file in date_dir.glob(f"rollout-*-{native_session_id}.jsonl"):
                    self._index_path(transcript_file)
                    with self._lock:
                        meta = self._by_thread_id.get(native_session_id)
                        if meta is not None:
                            return meta.transcript_path
                    return str(transcript_file)
            except (ValueError, OSError):
                continue

        for transcript_file in sessions_dir.rglob(f"rollout-*-{native_session_id}.jsonl"):
            self._index_path(transcript_file)
            with self._lock:
                meta = self._by_thread_id.get(native_session_id)
                if meta is not None:
                    return meta.transcript_path
            return str(transcript_file)
        return None

    def _index_path(self, transcript_path: Path) -> None:
        path_str = str(transcript_path)
        with self._lock:
            if path_str in self._known_paths:
                return

        meta = read_codex_transcript_meta(transcript_path)
        if meta is None:
            return

        with self._lock:
            if path_str in self._known_paths:
                return
            self._known_paths.add(path_str)
            self._by_path[path_str] = meta
            if meta.thread_id:
                self._by_thread_id[meta.thread_id] = meta
            if meta.parent_thread_id:
                children = self._children_by_parent.setdefault(meta.parent_thread_id, [])
                children.append(meta)
                children.sort(
                    key=lambda item: (
                        item.session_started_at is None,
                        item.session_started_at.isoformat() if item.session_started_at else "",
                        item.transcript_path,
                    )
                )


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


def _iter_codex_transcript_paths(sessions_dir: Path) -> Iterator[Path]:
    """Yield every Codex transcript path under the sessions directory."""
    if not sessions_dir.exists():
        return
    yield from sessions_dir.rglob("rollout-*.jsonl")


def _iter_candidate_date_dirs(started_at: datetime, now: datetime) -> Iterator[Path]:
    """Yield day directories spanning session creation through current time."""
    sessions_dir = _codex_sessions_dir()
    started = started_at.astimezone(UTC).date()
    finished = now.astimezone(UTC).date()
    day_span = max(0, (finished - started).days)
    bounded_span = min(day_span, _RECENT_DISCOVERY_DAYS)
    for days_offset in range(bounded_span + 1):
        current = started + timedelta(days=days_offset)
        yield sessions_dir / f"{current.year}" / f"{current.month:02d}" / f"{current.day:02d}"


def _parse_native_session_id_from_rollout_name(path: Path) -> str | None:
    """Extract the native Codex thread id from a rollout filename."""
    match = _ROLLOUT_FILENAME_RE.match(path.name)
    if not match:
        return None
    return match.group("native_session_id")


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
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(raw, dict) or raw.get("type") != "session_meta":
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


def discover_codex_transcript_family_meta(
    *,
    root_transcript_path: str | None = None,
    root_thread_id: str | None = None,
) -> list[CodexTranscriptMeta]:
    """Resolve parent and descendant Codex transcript metadata recursively."""
    return _get_transcript_index().discover_family_meta(
        root_transcript_path=root_transcript_path,
        root_thread_id=root_thread_id,
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

    logger.warning("Codex transcript not found", native_session_id=native_session_id)
    return None


def discover_recent_unclaimed_codex_transcript(
    *,
    session_created_at: datetime | None,
    claimed_native_session_ids: Collection[str],
) -> CodexRecentTranscriptCandidate | None:
    """Resolve a unique recent Codex transcript candidate for an unbound session.

    The search is intentionally cheap:
    - only day directories spanning session creation through now
    - only rollout files newer than the TeleClaude session creation time
    - only native ids not already claimed by another TeleClaude session
    - only returns a result when exactly one candidate remains
    """
    if session_created_at is None:
        return None

    created_at = session_created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)

    cutoff_ts = created_at.timestamp()
    claimed_ids = {value.strip() for value in claimed_native_session_ids if value.strip()}
    now = datetime.now(UTC)

    discovered: dict[str, tuple[float, Path]] = {}
    for date_dir in _iter_candidate_date_dirs(created_at, now):
        if not date_dir.exists():
            continue
        try:
            rollout_files = sorted(
                (path for path in date_dir.glob("rollout-*.jsonl") if path.is_file()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            continue

        for transcript_path in rollout_files:
            native_session_id = _parse_native_session_id_from_rollout_name(transcript_path)
            if not native_session_id or native_session_id in claimed_ids:
                continue
            try:
                mtime = transcript_path.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff_ts:
                continue
            existing = discovered.get(native_session_id)
            if existing is None or mtime > existing[0]:
                discovered[native_session_id] = (mtime, transcript_path)

    if len(discovered) != 1:
        logger.debug(
            "Codex recent transcript candidate discovery did not resolve uniquely",
            candidate_count=len(discovered),
        )
        return None

    native_session_id, (_, transcript_path) = next(iter(discovered.items()))
    logger.debug(
        "Codex recent transcript candidate resolved",
        native_session_id=native_session_id,
        path=str(transcript_path),
    )
    return CodexRecentTranscriptCandidate(
        transcript_path=str(transcript_path),
        native_session_id=native_session_id,
    )


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
