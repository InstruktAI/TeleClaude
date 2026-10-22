"""Disposable normalized transcript views shared by projection consumers."""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Protocol

from teleclaude.agent_registry import AgentName
from teleclaude.core.models._types import JsonDict, JsonValue

from ._utils import _parse_timestamp
from .source_reader import SourceChange, SourceFormat, TranscriptSourceReader

_MAX_CACHED_TRANSCRIPTS = 8
_MAX_CACHED_SOURCE_BYTES = 384 * 1024 * 1024
_ENTRY_TIMESTAMP_FIELD = "timestamp"
_MIN_TIMESTAMP = datetime.min.replace(tzinfo=UTC)
_TRANSCRIPT_READ_SCOPE: ContextVar[_ReadScope | None] = ContextVar("transcript_read_scope", default=None)
type FormatMismatchHandler = Callable[[str, Path, json.JSONDecodeError], None]


class _ReadScope:
    """A pass-owned view whose inherited contexts expire with the pass."""

    def __init__(self) -> None:
        self.active = True
        self._entries: dict[tuple[Path, AgentName], list[JsonDict]] = {}
        self._lock = RLock()

    def get(self, key: tuple[Path, AgentName]) -> list[JsonDict] | None:
        with self._lock:
            return self._entries.get(key) if self.active else None

    def put(self, key: tuple[Path, AgentName], entries: list[JsonDict]) -> None:
        with self._lock:
            if self.active:
                self._entries[key] = entries

    def close(self) -> None:
        with self._lock:
            self.active = False
            self._entries.clear()


class TranscriptCodec(Protocol):
    """Provider-owned record interpretation consumed by the shared view owner."""

    @property
    def normalize(self) -> Callable[[Iterable[JsonDict]], Iterable[JsonDict]]: ...

    @property
    def document_records(self) -> Callable[[JsonValue], Iterable[JsonDict]]: ...

    @property
    def append_anchor(self) -> Callable[[JsonDict], bool] | None: ...

    @property
    def format_mismatch_agent(self) -> str | None: ...


class TranscriptEntries(list[JsonDict]):
    """Stable source entries with a seek index that preserves native record order."""

    def __init__(self, snapshot: tuple[JsonDict, ...], timestamp_maxima: tuple[datetime, ...]) -> None:
        super().__init__(snapshot)
        self.snapshot = snapshot
        self.timestamp_maxima = timestamp_maxima


def _copy_entry_view(entries: list[JsonDict]) -> list[JsonDict]:
    """Copy the public list structure while sharing read-only normalized records."""
    if isinstance(entries, TranscriptEntries):
        return TranscriptEntries(entries.snapshot, entries.timestamp_maxima)
    return list(entries)


class _TranscriptView:
    """One synchronized source cursor and its complete normalized view."""

    def __init__(self, reader: TranscriptCodec, report_mismatch: FormatMismatchHandler) -> None:
        self.reader = reader
        self.report_mismatch = report_mismatch
        self.source = TranscriptSourceReader()
        self.lock = RLock()
        self.entries: tuple[JsonDict, ...] = ()
        self.timestamp_maxima: tuple[datetime, ...] = ()
        self.anchor: JsonDict | None = None
        self.cached_bytes = 0

    def read(self, path: Path) -> list[JsonDict]:
        with self.lock:
            try:
                batch = self.source.read(path)
                if batch.change is SourceChange.UNCHANGED:
                    return TranscriptEntries(self.entries, self.timestamp_maxima)
                if batch.decode_error is not None and not batch.records and self.reader.format_mismatch_agent:
                    self.report_mismatch(self.reader.format_mismatch_agent, path, batch.decode_error)
                records = list(
                    self.reader.document_records(batch.document) if batch.format is SourceFormat.JSON else batch.records
                )
                prefix = self.entries if batch.change is SourceChange.APPENDED else ()
                if batch.change is SourceChange.REPLACED:
                    self.anchor = None
                incoming = records
                if self.anchor is not None:
                    count = len(tuple(self.reader.normalize((self.anchor,))))
                    if count:
                        prefix = prefix[:-count]
                    incoming = [self.anchor, *records]
                normalized = tuple(self.reader.normalize(incoming))
                maxima = list(self.timestamp_maxima[: len(prefix)])
                maximum = maxima[-1] if maxima else _MIN_TIMESTAMP
                for entry in normalized:
                    raw_time = entry.get(_ENTRY_TIMESTAMP_FIELD)
                    timestamp = _parse_timestamp(raw_time) if isinstance(raw_time, str) else None
                    if timestamp is not None:
                        maximum = max(maximum, timestamp)
                    maxima.append(maximum)
                if self.reader.append_anchor is not None:
                    for record in records:
                        if self.reader.append_anchor(record):
                            self.anchor = record
                self.entries = (*prefix, *normalized)
                self.timestamp_maxima = tuple(maxima)
                self.cached_bytes = self.source.decoded_bytes
                return TranscriptEntries(self.entries, self.timestamp_maxima)
            except Exception:
                self.source.reset()
                raise


_TRANSCRIPT_VIEWS: OrderedDict[tuple[Path, AgentName], _TranscriptView] = OrderedDict()
_TRANSCRIPT_VIEWS_LOCK = RLock()


@contextmanager
def transcript_read_scope() -> Iterator[None]:
    """Pin each source's normalized view throughout one composed projection pass."""
    scope = _ReadScope()
    token = _TRANSCRIPT_READ_SCOPE.set(scope)
    try:
        yield
    finally:
        scope.close()
        _TRANSCRIPT_READ_SCOPE.reset(token)


def clear_transcript_source(path: str) -> None:
    """Release disposable source views when their owning session ends."""
    source_path = Path(path).expanduser()
    with _TRANSCRIPT_VIEWS_LOCK:
        for key in tuple(_TRANSCRIPT_VIEWS):
            if key[0] == source_path:
                del _TRANSCRIPT_VIEWS[key]


def _cached_entries(
    path: Path, agent_name: AgentName, reader: TranscriptCodec, report_mismatch: FormatMismatchHandler
) -> list[JsonDict]:
    key = (path, agent_name)
    with _TRANSCRIPT_VIEWS_LOCK:
        view = _TRANSCRIPT_VIEWS.get(key)
        if view is None:
            view = _TranscriptView(reader, report_mismatch)
            _TRANSCRIPT_VIEWS[key] = view
        _TRANSCRIPT_VIEWS.move_to_end(key)
    try:
        result = view.read(path)
    except json.JSONDecodeError as exc:
        if view.reader.format_mismatch_agent is None:
            raise
        report_mismatch(view.reader.format_mismatch_agent, path, exc)
        return []
    with _TRANSCRIPT_VIEWS_LOCK:
        if _TRANSCRIPT_VIEWS.get(key) is view:
            _TRANSCRIPT_VIEWS.move_to_end(key)
            # Keep one oversized source useful; evict older views rather than
            # excluding the large transcripts that need incremental reads most.
            while len(_TRANSCRIPT_VIEWS) > 1 and (
                len(_TRANSCRIPT_VIEWS) > _MAX_CACHED_TRANSCRIPTS
                or sum(item.cached_bytes for item in _TRANSCRIPT_VIEWS.values()) > _MAX_CACHED_SOURCE_BYTES
            ):
                _TRANSCRIPT_VIEWS.popitem(last=False)
    return result


def read_transcript_entries(
    path: Path, agent_name: AgentName, reader: TranscriptCodec, report_mismatch: FormatMismatchHandler
) -> list[JsonDict] | None:
    """Reuse a pinned or current view without changing its delivery obligations."""
    scope = _TRANSCRIPT_READ_SCOPE.get()
    key = (path, agent_name)
    pinned = scope.get(key) if scope is not None else None
    if pinned is not None:
        return _copy_entry_view(pinned)
    if not path.exists():
        return None
    entries = _cached_entries(path, agent_name, reader, report_mismatch)
    if scope is not None:
        scope.put(key, entries)
    return entries
