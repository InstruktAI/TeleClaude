"""Write and state reads for session-owned conversation mirrors.

One mirror row holds one TeleClaude session's conversation; each native transcript that holds part of
it is a source row beneath it, with the source's conversational messages. The conversation text is the
sources' rendered text in lineage order, and the mirror records how completely its sources were read.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Connection, text
from sqlalchemy.engine import Row
from sqlalchemy.exc import OperationalError as SqlAlchemyOperationalError

from teleclaude.mirrors._attribution import MirrorSessionAttribution, upsert_session_attribution
from teleclaude.mirrors._types import JsonValue
from teleclaude.mirrors.store import (
    _BEGIN_IMMEDIATE_SQL,
    _get_ro_engine,
    _get_rw_engine,
    _int_value,
    _is_missing_table_error,
    _optional_int,
    _optional_str,
    _parse_metadata,
)

_SEGMENT_SEPARATOR = "\n\n"
_EMPTY_TEXT = ""
_SOURCE_PARAM_PREFIX = "source_"

_MIRROR_STATE_COLUMNS = """\
mirrors.id, mirrors.created_at, mirrors.title, mirrors.covered_at, mirrors.coverage_ready,
    mirrors.conversation_text, mirrors.metadata, mirror_sessions.session_id
"""
_SELECT_MIRROR_BY_SESSION_ID_SQL = (
    f"SELECT {_MIRROR_STATE_COLUMNS} FROM mirrors JOIN mirror_sessions ON mirror_sessions.id = mirrors.session "
    "WHERE mirror_sessions.session_id = :session_id"
)
_SELECT_MIRROR_BY_SESSION_SQL = (
    f"SELECT {_MIRROR_STATE_COLUMNS} FROM mirrors LEFT JOIN mirror_sessions ON mirror_sessions.id = mirrors.session "
    "WHERE mirrors.session = :session"
)
_SELECT_MIRROR_BY_SOURCES_SQL = (
    f"SELECT {_MIRROR_STATE_COLUMNS} FROM mirrors LEFT JOIN mirror_sessions ON mirror_sessions.id = mirrors.session "
    "WHERE mirrors.id = (SELECT mirror FROM mirror_sources WHERE source_identity IN ({placeholders}) "
    "ORDER BY position DESC LIMIT 1)"
)
_SELECT_SOURCE_STATES_SQL = """\
SELECT id, source_identity, native_session_id, agent, transcript_path, position, file_size, file_mtime_ns,
    missing_at, derivation_version, message_count,
    EXISTS (SELECT 1 FROM mirror_messages WHERE mirror_messages.source = mirror_sources.id) AS has_messages
FROM mirror_sources WHERE mirror = :mirror ORDER BY position, id
"""
_UPSERT_SOURCE_SQL = """\
INSERT INTO mirror_sources (
    mirror, source_identity, native_session_id, agent, transcript_path, position, file_size, file_mtime_ns,
    missing_at, derivation_version, created_at, updated_at
) VALUES (
    :mirror, :source_identity, :native_session_id, :agent, :transcript_path, :position, :file_size, :file_mtime_ns,
    :missing_at, :derivation_version, :now, :now
)
ON CONFLICT(source_identity) DO UPDATE SET
    mirror = excluded.mirror,
    native_session_id = COALESCE(excluded.native_session_id, mirror_sources.native_session_id),
    agent = excluded.agent,
    transcript_path = COALESCE(excluded.transcript_path, mirror_sources.transcript_path),
    position = excluded.position,
    file_size = COALESCE(excluded.file_size, mirror_sources.file_size),
    file_mtime_ns = COALESCE(excluded.file_mtime_ns, mirror_sources.file_mtime_ns),
    missing_at = excluded.missing_at,
    derivation_version = excluded.derivation_version,
    updated_at = excluded.updated_at
"""
_SELECT_SOURCE_OBSERVATION_SQL = "SELECT file_mtime_ns FROM mirror_sources WHERE source_identity = :source_identity"
_SELECT_SOURCE_ID_SQL = "SELECT id FROM mirror_sources WHERE source_identity = :source_identity"
_DELETE_SOURCE_MESSAGES_SQL = "DELETE FROM mirror_messages WHERE source = :source"
_INSERT_MESSAGE_SQL = """\
INSERT INTO mirror_messages (source, ordinal, entry_index, block_ordinal, timestamp, role, text)
VALUES (:source, :ordinal, :entry_index, :block_ordinal, :timestamp, :role, :text)
"""
_REPLACE_SOURCE_CONTENT_SQL = """\
UPDATE mirror_sources SET archival_text = '', message_count = :message_count,
    timestamp_start = :timestamp_start, timestamp_end = :timestamp_end
WHERE id = :source
"""
_SELECT_SOURCES_FOR_RENDER_SQL = """\
SELECT id, source_identity, native_session_id, agent, transcript_path, derivation_version, archival_text,
    message_count, timestamp_start, timestamp_end, missing_at
FROM mirror_sources WHERE mirror = :mirror ORDER BY position, id
"""
_SELECT_SOURCE_MESSAGES_SQL = (
    "SELECT timestamp, role, text FROM mirror_messages WHERE source = :source ORDER BY ordinal"
)
_INSERT_MIRROR_SQL = """\
INSERT INTO mirrors (
    native_session_id, source_identity, computer, agent, project_path, title, conversation_text, metadata,
    created_at, updated_at, human_email, visibility, command, todo, is_worker, session
) VALUES (
    :native_session_id, :source_identity, COALESCE(:computer, ''), :agent, COALESCE(:project_path, ''),
    COALESCE(:title, ''), '', :metadata, :created_at, :updated_at, :human_email, COALESCE(:visibility, 'private'),
    :command, :todo, COALESCE(:is_worker, 0), :session
)
"""
_UPDATE_MIRROR_SQL = """\
UPDATE mirrors SET
    native_session_id = :native_session_id,
    source_identity = :source_identity,
    session = COALESCE(:session, session),
    computer = COALESCE(NULLIF(:computer, ''), computer),
    agent = :agent,
    project_path = COALESCE(NULLIF(:project_path, ''), project_path),
    title = COALESCE(NULLIF(:title, ''), title),
    timestamp_start = :timestamp_start,
    timestamp_end = :timestamp_end,
    conversation_text = :conversation_text,
    message_count = :message_count,
    metadata = :metadata,
    updated_at = :updated_at,
    human_email = COALESCE(NULLIF(:human_email, ''), human_email),
    visibility = COALESCE(NULLIF(:visibility, ''), visibility),
    command = COALESCE(NULLIF(:command, ''), command),
    todo = COALESCE(NULLIF(:todo, ''), todo),
    is_worker = COALESCE(:is_worker, is_worker),
    derivation_version = :derivation_version,
    covered_at = :covered_at,
    coverage_ready = :coverage_ready
WHERE id = :id
"""
_RESET_READINESS_SQL = (
    "UPDATE mirrors SET coverage_ready = 0 WHERE session = "
    "(SELECT id FROM mirror_sessions WHERE session_id = :session_id)"
)
_ATTRIBUTE_MIRROR_SQL = "UPDATE mirrors SET session = :session WHERE id = :id AND session IS NULL"
_SELECT_HOLDING_MIRRORS_SQL = "SELECT DISTINCT mirror FROM mirror_sources WHERE source_identity IN ({placeholders})"
_COUNT_MIRROR_SOURCES_SQL = "SELECT COUNT(*) FROM mirror_sources WHERE mirror = :mirror"
_DELETE_EMPTY_MIRROR_SQL = "DELETE FROM mirrors WHERE id = :mirror"
_STAMP_COVERAGE_SQL = """\
UPDATE mirrors SET
    coverage_ready = CASE WHEN covered_at IS NULL OR :covered_at >= covered_at THEN :coverage_ready ELSE coverage_ready END,
    covered_at = CASE WHEN covered_at IS NULL OR :covered_at >= covered_at THEN :covered_at ELSE covered_at END
WHERE id = :id
"""
_SELECT_COVERAGE_SQL = "SELECT covered_at, coverage_ready FROM mirrors WHERE id = :id"
_SELECT_SOURCE_FACTS_SQL = (
    "SELECT source_identity, native_session_id, transcript_path, message_count, missing_at "
    "FROM mirror_sources WHERE mirror = :mirror ORDER BY position, id"
)
_CLEAR_UNREPROJECTABLE_SQL = "DELETE FROM mirror_unreprojectable_sources WHERE source_identity = :source_identity"
_CLEAR_SHRINK_REFUSAL_SQL = "DELETE FROM mirror_shrink_refusals WHERE source_identity = :source_identity"
_TRANSCRIPT_PATH_FIELD = "transcript_path"


@dataclass(frozen=True)
class SourceMessage:
    """One conversational message of a source, keyed within the source by its transcript entry and block."""

    entry_index: int
    block_ordinal: int
    timestamp: str | None
    role: str
    text: str


@dataclass(frozen=True)
class SourceUpdate:
    """What one refresh learned about one native source of a conversation.

    ``messages`` of ``None`` keeps the content the store already holds for the source (it was unchanged,
    its file is gone, or a shorter read was refused); ``derivation_version`` then states the derivation of
    that kept content.
    """

    source_identity: str
    native_session_id: str | None
    agent: str
    transcript_path: str | None
    position: int
    file_size: int | None
    file_mtime_ns: str | None
    missing: bool
    derivation_version: int
    messages: tuple[SourceMessage, ...] | None


@dataclass(frozen=True)
class ConversationFacts:
    """The launch and identity facts a conversation mirror records beside its sources."""

    computer: str | None
    project_path: str | None
    title: str | None
    human_email: str | None
    visibility: str | None
    command: str | None
    todo: str | None
    is_worker: bool | None
    metadata: dict[str, JsonValue]


@dataclass(frozen=True)
class ConversationUpdate:
    """One refresh's complete write: facts, attribution, every source observed, and the coverage reached."""

    facts: ConversationFacts
    attribution: MirrorSessionAttribution | None
    sources: tuple[SourceUpdate, ...]
    covered_at: str
    ready: bool


@dataclass(frozen=True)
class MissingSource:
    """A lineage source whose transcript file no longer exists; its retained content stays in the mirror."""

    source_identity: str
    native_session_id: str | None
    transcript_path: str | None


@dataclass(frozen=True)
class RecordedCoverage:
    """The coverage a mirror holds after a refresh recorded it, read in the transaction that recorded it.

    Time, readiness, message count and source completeness describe one committed observation.
    """

    covered_at: str | None
    ready: bool
    message_count: int
    missing_sources: tuple[MissingSource, ...]


@dataclass(frozen=True)
class ConversationWriteResult:
    """What a conversation write left in the store."""

    mirror_id: int
    text_changed: bool
    coverage: RecordedCoverage


@dataclass(frozen=True)
class SourceState:
    """A source as the store holds it."""

    id: int
    source_identity: str
    native_session_id: str | None
    agent: str
    transcript_path: str | None
    position: int
    file_size: int | None
    file_mtime_ns: str | None
    missing_at: str | None
    derivation_version: int
    message_count: int
    has_messages: bool


@dataclass(frozen=True)
class ConversationState:
    """A conversation mirror as the store holds it, with its sources in lineage order."""

    mirror_id: int
    session_id: str | None
    created_at: str
    title: str | None
    covered_at: str | None
    coverage_ready: bool
    sources: tuple[SourceState, ...]

    def source(self, source_identity: str) -> SourceState | None:
        """The stored source with this identity, if the conversation holds it."""
        return next((source for source in self.sources if source.source_identity == source_identity), None)


def _bind_sources(source_identities: Sequence[str]) -> tuple[str, dict[str, object]]:  # guard: loose-dict - SQL binds
    """SQL placeholders and bind values for a set of source identities."""
    names = [f"{_SOURCE_PARAM_PREFIX}{index}" for index in range(len(source_identities))]
    return ", ".join(f":{name}" for name in names), dict(zip(names, source_identities, strict=True))


def _source_state(row: Row[Any]) -> SourceState:
    return SourceState(
        id=_int_value(row.id),
        source_identity=str(row.source_identity),
        native_session_id=_optional_str(row.native_session_id),
        agent=str(row.agent),
        transcript_path=_optional_str(row.transcript_path),
        position=_int_value(row.position),
        file_size=_optional_int(row.file_size),
        file_mtime_ns=_optional_str(row.file_mtime_ns),
        missing_at=_optional_str(row.missing_at),
        derivation_version=_int_value(row.derivation_version),
        message_count=_int_value(row.message_count),
        has_messages=bool(row.has_messages),
    )


def _conversation_state(row: Row[Any], sources: Sequence[Row[Any]]) -> ConversationState:
    return ConversationState(
        mirror_id=_int_value(row.id),
        session_id=_optional_str(row.session_id),
        created_at=str(row.created_at),
        title=_optional_str(row.title),
        covered_at=_optional_str(row.covered_at),
        coverage_ready=bool(row.coverage_ready),
        sources=tuple(_source_state(source) for source in sources),
    )


def get_conversation_state(
    *,
    session_id: str | None,
    source_identities: Sequence[str],
    db: str | Path | None = None,
) -> ConversationState | None:
    """Read the conversation mirror a session owns, or else the one that already holds any of these sources."""
    try:
        with _get_ro_engine(db).connect() as conn:
            row = None
            if session_id is not None:
                row = conn.execute(text(_SELECT_MIRROR_BY_SESSION_ID_SQL), dict(session_id=session_id)).first()
            if row is None and source_identities:
                placeholders, params = _bind_sources(source_identities)
                row = conn.execute(
                    text(_SELECT_MIRROR_BY_SOURCES_SQL.format(placeholders=placeholders)), params
                ).first()
            if row is None:
                return None
            sources = conn.execute(text(_SELECT_SOURCE_STATES_SQL), dict(mirror=row.id)).all()
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return None
        raise
    return _conversation_state(row, sources)


def _render_message(timestamp: str | None, role: str, message_text: str) -> str:
    speaker = role.capitalize()
    return f"[{timestamp}] {speaker}: {message_text}" if timestamp is not None else f"{speaker}: {message_text}"


def render_source(conn: Connection, source_id: int, archival_text: str | None) -> str:
    """A source's rendered text: its messages, or the archival segment it was consolidated from."""
    messages = conn.execute(text(_SELECT_SOURCE_MESSAGES_SQL), dict(source=source_id)).all()
    if not messages:
        return str(archival_text or _EMPTY_TEXT)
    return _SEGMENT_SEPARATOR.join(
        _render_message(_optional_str(row.timestamp), str(row.role), str(row.text)) for row in messages
    )


def _merge_metadata(stored: dict[str, JsonValue], supplied: dict[str, JsonValue]) -> dict[str, JsonValue]:
    merged = dict(stored)
    merged.update({key: value for key, value in supplied.items() if value is not None or key not in stored})
    return merged


def _is_older_observation(conn: Connection, update: SourceUpdate) -> bool:
    """Whether the store already holds a newer observation of this source's file than the one this update read."""
    if update.file_mtime_ns is None:
        return False
    stored = conn.execute(text(_SELECT_SOURCE_OBSERVATION_SQL), dict(source_identity=update.source_identity)).scalar()
    return stored is not None and int(stored) > int(update.file_mtime_ns)


def _apply_source(conn: Connection, mirror_id: int, update: SourceUpdate, now: str) -> None:
    """Upsert one source row and, when it was re-read, replace its messages."""
    conn.execute(
        text(_UPSERT_SOURCE_SQL),
        dict(
            mirror=mirror_id,
            source_identity=update.source_identity,
            native_session_id=update.native_session_id,
            agent=update.agent,
            transcript_path=update.transcript_path,
            position=update.position,
            file_size=update.file_size,
            file_mtime_ns=update.file_mtime_ns,
            missing_at=now if update.missing else None,
            derivation_version=update.derivation_version,
            now=now,
        ),
    )
    if update.messages is None:
        return
    source_id = conn.execute(text(_SELECT_SOURCE_ID_SQL), dict(source_identity=update.source_identity)).scalar_one()
    conn.execute(text(_DELETE_SOURCE_MESSAGES_SQL), dict(source=source_id))
    if update.messages:
        conn.execute(
            text(_INSERT_MESSAGE_SQL),
            [
                dict(
                    source=source_id,
                    ordinal=ordinal,
                    entry_index=message.entry_index,
                    block_ordinal=message.block_ordinal,
                    timestamp=message.timestamp,
                    role=message.role,
                    text=message.text,
                )
                for ordinal, message in enumerate(update.messages)
            ],
        )
    conn.execute(
        text(_REPLACE_SOURCE_CONTENT_SQL),
        dict(
            source=source_id,
            message_count=len(update.messages),
            timestamp_start=update.messages[0].timestamp if update.messages else None,
            timestamp_end=update.messages[-1].timestamp if update.messages else None,
        ),
    )
    conn.execute(text(_CLEAR_UNREPROJECTABLE_SQL), dict(source_identity=update.source_identity))
    conn.execute(text(_CLEAR_SHRINK_REFUSAL_SQL), dict(source_identity=update.source_identity))


@dataclass(frozen=True)
class _ImpliedMirror:
    """The conversation columns a mirror's sources imply."""

    conversation_text: str
    message_count: int
    timestamp_start: str | None
    timestamp_end: str | None
    native_session_id: str | None
    source_identity: str
    agent: str
    derivation_version: int
    transcript_path: str | None


def _implied_mirror(conn: Connection, mirror_id: int) -> _ImpliedMirror:
    """The conversation columns the mirror's sources imply."""
    sources = conn.execute(text(_SELECT_SOURCES_FOR_RENDER_SQL), dict(mirror=mirror_id)).all()
    segments = [
        segment for segment in (render_source(conn, source.id, source.archival_text) for source in sources) if segment
    ]
    starts = [source.timestamp_start for source in sources if source.timestamp_start]
    ends = [source.timestamp_end for source in sources if source.timestamp_end]
    newest = sources[-1]
    return _ImpliedMirror(
        conversation_text=_SEGMENT_SEPARATOR.join(segments),
        message_count=sum(_int_value(source.message_count) for source in sources),
        timestamp_start=starts[0] if starts else None,
        timestamp_end=ends[-1] if ends else None,
        native_session_id=newest.native_session_id,
        source_identity=newest.source_identity,
        agent=newest.agent,
        derivation_version=min(_int_value(source.derivation_version) for source in sources),
        transcript_path=_optional_str(newest.transcript_path),
    )


def _create_mirror(conn: Connection, update: ConversationUpdate, session: int | None, now: str) -> int:
    first = update.sources[-1]
    result = conn.execute(
        text(_INSERT_MIRROR_SQL),
        {
            "native_session_id": first.native_session_id,
            "source_identity": first.source_identity,
            "agent": first.agent,
            "computer": update.facts.computer,
            "project_path": update.facts.project_path,
            "title": update.facts.title,
            "metadata": json.dumps({}),
            "created_at": now,
            "updated_at": now,
            "human_email": update.facts.human_email,
            "visibility": update.facts.visibility,
            "command": update.facts.command,
            "todo": update.facts.todo,
            "is_worker": None if update.facts.is_worker is None else int(update.facts.is_worker),
            "session": session,
        },
    )
    return int(result.lastrowid)


def _reap_emptied_mirrors(conn: Connection, previous_mirror_ids: set[int], mirror_id: int) -> None:
    """Remove a conversation mirror whose every source moved to another conversation, so it cannot duplicate it."""
    for previous in previous_mirror_ids - {mirror_id}:
        if conn.execute(text(_COUNT_MIRROR_SOURCES_SQL), {"mirror": previous}).scalar_one() == 0:
            conn.execute(text(_DELETE_EMPTY_MIRROR_SQL), {"mirror": previous})


def _holding_mirrors(conn: Connection, source_identities: Sequence[str]) -> set[int]:
    placeholders, params = _bind_sources(source_identities)
    rows = conn.execute(text(_SELECT_HOLDING_MIRRORS_SQL.format(placeholders=placeholders)), params).scalars().all()
    return {int(row) for row in rows}


def _find_mirror(conn: Connection, session: int | None, source_identities: Sequence[str]) -> Row[Any] | None:
    if session is not None:
        return conn.execute(text(_SELECT_MIRROR_BY_SESSION_SQL), dict(session=session)).first()
    placeholders, params = _bind_sources(source_identities)
    return conn.execute(text(_SELECT_MIRROR_BY_SOURCES_SQL.format(placeholders=placeholders)), params).first()


def reset_coverage_readiness(session_id: str, *, db: str | Path | None = None) -> None:
    """Mark a session's mirror not ready, so the next refresh that reads it reports coverage again."""
    with _get_rw_engine(db).begin() as conn:
        conn.execute(text(_RESET_READINESS_SQL), {"session_id": session_id})


def attribute_mirror(mirror_id: int, attribution: MirrorSessionAttribution, *, db: str | Path | None = None) -> None:
    """Attribute a mirror no session claimed to the archive session that now retains it."""
    now = datetime.now(UTC).isoformat()
    with _get_rw_engine(db).connect() as conn:
        conn.exec_driver_sql(_BEGIN_IMMEDIATE_SQL)  # guard: raw-sql - serialize with other mirror writes.
        try:
            session = upsert_session_attribution(
                cast(sqlite3.Connection, conn.connection.driver_connection), attribution, now
            )
            conn.execute(text(_ATTRIBUTE_MIRROR_SQL), {"id": mirror_id, "session": session})
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _recorded_coverage(conn: Connection, mirror_id: int) -> RecordedCoverage:
    """Read, inside the recording transaction, the coverage the mirror now holds and the facts it covers."""
    recorded = conn.execute(text(_SELECT_COVERAGE_SQL), dict(id=mirror_id)).one()
    sources = conn.execute(text(_SELECT_SOURCE_FACTS_SQL), dict(mirror=mirror_id)).all()
    return RecordedCoverage(
        covered_at=_optional_str(recorded.covered_at),
        ready=bool(recorded.coverage_ready),
        message_count=sum(_int_value(source.message_count) for source in sources),
        missing_sources=tuple(
            MissingSource(
                source_identity=str(source.source_identity),
                native_session_id=_optional_str(source.native_session_id),
                transcript_path=_optional_str(source.transcript_path),
            )
            for source in sources
            if source.missing_at is not None
        ),
    )


def stamp_coverage(mirror_id: int, *, covered_at: str, ready: bool, db: str | Path | None = None) -> RecordedCoverage:
    """Record a confirmed read of an unchanged conversation without rewriting its text.

    Coverage only moves forward: an older observation leaves the newer one. The coverage that results is read in
    the same transaction, so what is returned is what was committed.
    """
    with _get_rw_engine(db).begin() as conn:
        conn.execute(text(_STAMP_COVERAGE_SQL), dict(id=mirror_id, covered_at=covered_at, coverage_ready=int(ready)))
        return _recorded_coverage(conn, mirror_id)


def write_conversation(update: ConversationUpdate, *, db: str | Path | None = None) -> ConversationWriteResult:
    """Write one refresh atomically: attribution, observed sources and messages, then the conversation they imply."""
    if not update.sources:
        raise ValueError("A conversation write needs at least one source")
    now = datetime.now(UTC).isoformat()
    with _get_rw_engine(db).connect() as conn:
        conn.exec_driver_sql(_BEGIN_IMMEDIATE_SQL)  # guard: raw-sql - serialize with other mirror writes.
        try:
            session = (
                upsert_session_attribution(
                    cast(sqlite3.Connection, conn.connection.driver_connection), update.attribution, now
                )
                if update.attribution is not None
                else None
            )
            stored = _find_mirror(conn, session, [source.source_identity for source in update.sources])
            mirror_id = stored.id if stored is not None else _create_mirror(conn, update, session, now)
            previous_text = str(stored.conversation_text) if stored is not None else _EMPTY_TEXT
            stored_metadata = _parse_metadata(stored.metadata) if stored is not None else {}
            previous_holders = _holding_mirrors(conn, [source.source_identity for source in update.sources])
            superseded = False
            for source in update.sources:
                if _is_older_observation(conn, source):
                    superseded = True
                    continue
                _apply_source(conn, mirror_id, source, now)
            _reap_emptied_mirrors(conn, previous_holders, mirror_id)
            implied = _implied_mirror(conn, mirror_id)
            metadata = _merge_metadata(stored_metadata, update.facts.metadata)
            if implied.transcript_path:
                metadata[_TRANSCRIPT_PATH_FIELD] = implied.transcript_path
            facts = update.facts
            # A refresh that observed less than the store already holds leaves the newer recorded coverage as it is.
            recorded_at = _optional_str(stored.covered_at) if stored is not None else None
            keeps_stored = recorded_at is not None and (superseded or update.covered_at < recorded_at)
            covered_at = recorded_at if keeps_stored and stored is not None else update.covered_at
            ready = bool(stored.coverage_ready) if keeps_stored and stored is not None else update.ready
            conn.execute(
                text(_UPDATE_MIRROR_SQL),
                dict(
                    native_session_id=implied.native_session_id,
                    source_identity=implied.source_identity,
                    agent=implied.agent,
                    timestamp_start=implied.timestamp_start,
                    timestamp_end=implied.timestamp_end,
                    conversation_text=implied.conversation_text,
                    message_count=implied.message_count,
                    derivation_version=implied.derivation_version,
                    id=mirror_id,
                    session=session,
                    computer=facts.computer,
                    project_path=facts.project_path,
                    title=facts.title,
                    human_email=facts.human_email,
                    visibility=facts.visibility,
                    command=facts.command,
                    todo=facts.todo,
                    is_worker=None if facts.is_worker is None else int(facts.is_worker),
                    metadata=json.dumps(metadata, sort_keys=True),
                    updated_at=now,
                    covered_at=covered_at,
                    coverage_ready=int(ready),
                ),
            )
            coverage = _recorded_coverage(conn, mirror_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return ConversationWriteResult(
        mirror_id=mirror_id,
        text_changed=previous_text != implied.conversation_text,
        coverage=coverage,
    )
