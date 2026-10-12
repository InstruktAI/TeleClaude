"""The conversational messages a session's mirror holds, with stable keys and the coverage that backs them.

This is the mirror's published conversation reader: other contexts take a session's messages and its coverage
from here and never from mirror storage. Messages come in lineage order, already conversation-only; a message's
key names its source and its place in that source, so it stays the same across compaction, native rotation and
re-derivation of an append-only source.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import OperationalError as SqlAlchemyOperationalError

from .conversations import MissingSource
from .store import _get_ro_engine, _int_value, _is_missing_table_error, _optional_str

_ARCHIVAL_ROLE = "archive"
_SELECT_MIRROR_SQL = """\
SELECT mirrors.id, mirrors.covered_at, mirrors.coverage_ready
FROM mirrors JOIN mirror_sessions ON mirror_sessions.id = mirrors.session
WHERE mirror_sessions.session_id = :session_id
"""
_SELECT_SOURCES_SQL = """\
SELECT id, source_identity, native_session_id, transcript_path, position, archival_text, timestamp_start,
    timestamp_end, missing_at
FROM mirror_sources WHERE mirror = :mirror ORDER BY position, id
"""
_SELECT_MESSAGES_SQL = """\
SELECT entry_index, block_ordinal, timestamp, role, text FROM mirror_messages WHERE source = :source ORDER BY ordinal
"""


@dataclass(frozen=True)
class SessionCoverage:
    """How far a session's mirror covers its conversation, as the last refresh established it."""

    covered_at: str | None
    ready: bool
    missing_sources: tuple[MissingSource, ...]


@dataclass(frozen=True)
class ConversationMessage:
    """One conversational message, or one source's archival segment, with its stable key."""

    key: str
    source_identity: str
    position: int
    timestamp: str | None
    role: str
    text: str
    archival: bool


@dataclass(frozen=True)
class ConversationMessages:
    """A session's conversational messages in lineage order, with the coverage that backs them."""

    session_id: str
    messages: tuple[ConversationMessage, ...]
    coverage: SessionCoverage


def message_key(source_identity: str, entry_index: int, block_ordinal: int) -> str:
    """The key of a structured message: its source, its transcript entry and its block within the entry."""
    return json.dumps([source_identity, entry_index, block_ordinal])


def archival_key(source_identity: str) -> str:
    """The key of a source's archival segment, which is a single unit of its source."""
    return json.dumps([source_identity])


def _coverage(mirror: RowMapping, sources: Sequence[RowMapping]) -> SessionCoverage:
    return SessionCoverage(
        covered_at=_optional_str(mirror["covered_at"]),
        ready=bool(mirror["coverage_ready"]),
        missing_sources=tuple(
            MissingSource(
                str(source["source_identity"]),
                _optional_str(source["native_session_id"]),
                _optional_str(source["transcript_path"]),
            )
            for source in sources
            if source["missing_at"] is not None
        ),
    )


def read_conversation_messages(session_id: str, *, db: str | Path | None = None) -> ConversationMessages | None:
    """Read a session's conversational messages and coverage; ``None`` when the session has no mirror."""
    try:
        with _get_ro_engine(db).connect() as conn:
            mirror = conn.execute(text(_SELECT_MIRROR_SQL), {"session_id": session_id}).mappings().first()
            if mirror is None:
                return None
            sources = conn.execute(text(_SELECT_SOURCES_SQL), {"mirror": mirror["id"]}).mappings().all()
            messages: list[ConversationMessage] = []
            for source in sources:
                identity = str(source["source_identity"])
                position = _int_value(source["position"])
                rows = conn.execute(text(_SELECT_MESSAGES_SQL), {"source": source["id"]}).mappings().all()
                if rows:
                    messages.extend(
                        ConversationMessage(
                            key=message_key(identity, _int_value(row["entry_index"]), _int_value(row["block_ordinal"])),
                            source_identity=identity,
                            position=position,
                            timestamp=_optional_str(row["timestamp"]),
                            role=str(row["role"]),
                            text=str(row["text"]),
                            archival=False,
                        )
                        for row in rows
                    )
                elif source["archival_text"]:
                    messages.append(
                        ConversationMessage(
                            key=archival_key(identity),
                            source_identity=identity,
                            position=position,
                            timestamp=_optional_str(source["timestamp_end"])
                            or _optional_str(source["timestamp_start"]),
                            role=_ARCHIVAL_ROLE,
                            text=str(source["archival_text"]),
                            archival=True,
                        )
                    )
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return None
        raise
    return ConversationMessages(
        session_id=session_id,
        messages=tuple(messages),
        coverage=_coverage(mirror, sources),
    )


def read_session_coverage(session_id: str, *, db: str | Path | None = None) -> SessionCoverage | None:
    """Read how far a session's mirror covers its conversation; ``None`` when the session has no mirror."""
    try:
        with _get_ro_engine(db).connect() as conn:
            mirror = conn.execute(text(_SELECT_MIRROR_SQL), {"session_id": session_id}).mappings().first()
            if mirror is None:
                return None
            sources = conn.execute(text(_SELECT_SOURCES_SQL), {"mirror": mirror["id"]}).mappings().all()
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return None
        raise
    return _coverage(mirror, sources)
