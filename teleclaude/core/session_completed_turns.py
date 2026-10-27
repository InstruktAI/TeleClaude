"""Read a session's completed turns, in order, from its native transcript chain.

A turn is an exchange the agent answered: it opens at a native user entry that carries input and includes every
further input entry that arrives before the agent's next text. Turns are found from the transcript chain itself,
so a turn the runtime never projected while it was not running is still a turn. The first time the read finds a
turn it records the turn's ordinal, and the ordinal never changes.

The read never touches output generations: live delivery keeps its own turn boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName, resolve_parser_agent
from teleclaude.core.conversation_messages import peer_segments_from_entry
from teleclaude.core.dates import ensure_utc, parse_iso_datetime
from teleclaude.core.db import db
from teleclaude.core.inbound_types import TurnPartKind
from teleclaude.core.injected_text import (
    TranscriptCutSegment,
    TranscriptEntryKind,
    cut_transcript_entry,
    is_peer_opening,
)
from teleclaude.core.models import JsonDict, Session
from teleclaude.core.session_status import is_session_final
from teleclaude.core.session_transcript_chain import build_message_chain
from teleclaude.core.session_turn_store import SessionTurnStore
from teleclaude.core.turn_binding import bind_pending_native_turns, binding_id_for_native_entry
from teleclaude.utils.transcript import native_entry_id, normalize_transcript_entry_message
from teleclaude.utils.transcript._iterators import _get_entries_for_agent
from teleclaude.utils.transcript._user_turns import (
    UserContentOrigin,
    classify_user_content_blocks,
    is_user_tool_result_only_message,
)

logger = get_logger(__name__)

_IDENTITY_TEMPLATE = "{runtime}:{entry_id}"
_MISSING_IDENTITY_TEMPLATE = "{runtime}:missing:{digest}"
_MISSING_DIGEST_LENGTH = 16
_REPLY_SEPARATOR = "\n\n"
_ROLE_FIELD = "role"
_CONTENT_FIELD = "content"
_TIMESTAMP_FIELD = "timestamp"
_TYPE_FIELD = "type"
_TEXT_FIELD = "text"
_USER_ROLE = "user"
_ASSISTANT_ROLE = "assistant"
_ASSISTANT_TEXT_TYPES = frozenset({"text", "output_text"})
_CALLER_HEADER_RE = re.compile(r"^\[(?P<label>[^(\]]+?) \((?P<session_id>[^)\]]+)\) on ")
_PLATFORM_ENVELOPE_KINDS = frozenset(
    {TranscriptEntryKind.PLATFORM_CONTROL, TranscriptEntryKind.REMINDER, TranscriptEntryKind.COMMAND_LOADER}
)
_UNIDENTIFIED_ENTRY_EVENT = "completed_turns_entry_unidentified"
_UNREADABLE_CHAIN_FILE_EVENT = "completed_turns_chain_file_missing"
_UNKNOWN_HELD_TURN_EVENT = "completed_turns_held_turn_unknown"


class TurnInputKind(StrEnum):
    """Who authored one part of a turn's input."""

    PERSON = "person"
    PEER = "peer"
    PLATFORM = "platform"


class PersonChannel(StrEnum):
    """The channel a person's words arrived through."""

    GITHUB = "github"
    ELSEWHERE = "elsewhere"


@dataclass(frozen=True)
class TurnInputPart:
    """One authored part of a turn's input, in the order the session received it."""

    kind: TurnInputKind
    text: str
    channel: PersonChannel | None = None
    person_display: str | None = None
    person_login: str | None = None
    person_link: str | None = None
    peer_session_id: str | None = None
    peer_role: str | None = None


@dataclass(frozen=True)
class CompletedTurn:
    """A turn the agent answered, or one whose transcript can no longer be read.

    ``completed_at`` is when the turn's last entry was written; it is absent for an unreadable turn and when no
    entry of the turn carried a time.
    """

    identity: str
    ordinal: int
    completed_at: datetime | None
    input_parts: tuple[TurnInputPart, ...]
    reply: str
    unreadable: bool = False


@dataclass(frozen=True)
class _InputSegment:
    kind: TurnInputKind
    text: str
    peer_session_id: str | None = None
    peer_role: str | None = None


@dataclass(frozen=True)
class _InputEntry:
    entry_id: str | None
    segments: tuple[_InputSegment, ...]


@dataclass(frozen=True)
class _MissingSource:
    """A transcript file the session's chain names that no longer exists."""

    path: str


@dataclass
class _OpenTurn:
    identity: str
    source_missing: bool = False
    inputs: list[_InputEntry] = field(default_factory=list)
    reply: list[str] = field(default_factory=list)
    last_time: datetime | None = None


def _caller_segment(segment: TranscriptCutSegment) -> _InputSegment | None:
    """Read a caller identity envelope's sender from its opening header and its body."""
    if segment.opening is None or segment.body_span is None:
        return None
    header = _CALLER_HEADER_RE.match(segment.opening)
    body = segment.text[segment.body_span[0] - segment.span[0] : segment.body_span[1] - segment.span[0]].strip()
    if header is None or not body:
        return None
    return _InputSegment(
        TurnInputKind.PEER,
        body,
        peer_session_id=header.group("session_id"),
        peer_role=header.group("label"),
    )


def _peer_segment(segment: TranscriptCutSegment) -> _InputSegment | None:
    """Read a peer envelope's sender and body."""
    peers = peer_segments_from_entry(segment.text, occurred_at=datetime.now(UTC))
    if not peers:
        return None
    peer = peers[0]
    return _InputSegment(
        TurnInputKind.PEER,
        peer.body,
        peer_session_id=peer.original_source_session_id,
        peer_role=peer.author_job_role or peer.author.display,
    )


def _segments_of(segment: TranscriptCutSegment) -> list[_InputSegment]:
    """Turn one cut segment of an input position into authored input."""
    kind = segment.kind or TranscriptEntryKind.ORDINARY
    if kind in _PLATFORM_ENVELOPE_KINDS:
        return [_InputSegment(TurnInputKind.PLATFORM, segment.text)]
    if kind is TranscriptEntryKind.IDENTITY_CONTENT:
        opening = segment.opening or ""
        sender = _peer_segment(segment) if is_peer_opening(opening) else _caller_segment(segment)
        return [sender] if sender is not None else []
    text = segment.text.strip()
    return [_InputSegment(TurnInputKind.PERSON, text)] if text else []


def _input_segments(entry: JsonDict, agent: AgentName) -> tuple[_InputSegment, ...]:
    """Return the authored input a user entry carries; tool results and runtime-injected context carry none.

    A position the transcript classifier marks as runtime is input only when it is a platform envelope (a
    notification, reminder or control delivery); the runtime's own injected context is not what started the turn.
    """
    message = normalize_transcript_entry_message(entry)
    if not isinstance(message, Mapping) or message.get(_ROLE_FIELD) != _USER_ROLE:
        return ()
    if is_user_tool_result_only_message(message):
        return ()
    segments: list[_InputSegment] = []
    for position in classify_user_content_blocks(entry, agent):
        if position.text is None:
            continue
        cut = cut_transcript_entry(position.text, is_user_entry=True)
        if position.origin is UserContentOrigin.RUNTIME and not any(
            part.kind in _PLATFORM_ENVELOPE_KINDS for part in cut
        ):
            continue
        for part in cut:
            segments.extend(_segments_of(part))
    return tuple(segments)


def _assistant_texts(entry: JsonDict) -> list[str]:
    """Return the text blocks of an assistant entry, without tool activity or reasoning."""
    message = normalize_transcript_entry_message(entry)
    if not isinstance(message, Mapping) or message.get(_ROLE_FIELD) != _ASSISTANT_ROLE:
        return []
    content = message.get(_CONTENT_FIELD)
    if isinstance(content, str):
        return [content] if content.strip() else []
    if not isinstance(content, list):
        return []
    texts: list[str] = []
    for block in content:
        if not isinstance(block, Mapping) or block.get(_TYPE_FIELD) not in _ASSISTANT_TEXT_TYPES:
            continue
        text = block.get(_TEXT_FIELD)
        if isinstance(text, str) and text.strip():
            texts.append(text)
    return texts


def _entry_time(entry: JsonDict) -> datetime | None:
    raw = entry.get(_TIMESTAMP_FIELD)
    parsed = parse_iso_datetime(raw) if isinstance(raw, str) else None
    return ensure_utc(parsed) if parsed is not None else None


def _source_digest(path: str) -> str:
    """Name a transcript file of a session's chain, for the record of which files a read has taken turns from."""
    return hashlib.sha256(path.encode()).hexdigest()[:_MISSING_DIGEST_LENGTH]


def _derive_turns(stream: Sequence[JsonDict | _MissingSource], agent: AgentName) -> list[_OpenTurn]:
    """Cut one ordered entry stream into turns; a missing source stands as one turn that cannot be read."""
    turns: list[_OpenTurn] = []
    current: _OpenTurn | None = None
    for entry in stream:
        if isinstance(entry, _MissingSource):
            digest = _source_digest(entry.path)
            current = None
            turns.append(
                _OpenTurn(
                    identity=_MISSING_IDENTITY_TEMPLATE.format(runtime=agent.value, digest=digest), source_missing=True
                )
            )
            continue
        segments = _input_segments(entry, agent)
        if segments:
            entry_id = native_entry_id(entry, agent)
            if current is None or current.reply:
                if entry_id is None:
                    logger.debug(_UNIDENTIFIED_ENTRY_EVENT, runtime=agent.value)
                    current = None
                    continue
                current = _OpenTurn(identity=_IDENTITY_TEMPLATE.format(runtime=agent.value, entry_id=entry_id))
                turns.append(current)
            current.inputs.append(_InputEntry(entry_id, segments))
        elif current is not None:
            current.reply.extend(_assistant_texts(entry))
        entry_time = _entry_time(entry)
        if (
            current is not None
            and entry_time is not None
            and (current.last_time is None or entry_time > current.last_time)
        ):
            current.last_time = entry_time
    return turns


def _read_chain(
    chain: Sequence[str], agent: AgentName, *, work_completed: bool, recorded_sources: frozenset[str]
) -> tuple[list[_OpenTurn], list[str]]:
    """Read every file of the chain, oldest first, into one turn sequence, and name the files that were read.

    A file the chain names that is gone stands in the sequence as a turn that cannot be read when the session has
    stopped at least once and so completed work somewhere, and no earlier read took turns from that file: whatever
    it held was deleted before it was taken. A file an earlier read took turns from needs no stand-in, since those
    turns are recorded under their own identities and ordinals.
    """
    stream: list[JsonDict | _MissingSource] = []
    read: list[str] = []
    for path in chain:
        file_entries = _get_entries_for_agent(path, agent)
        if file_entries is None:
            logger.warning(_UNREADABLE_CHAIN_FILE_EVENT, file=Path(path).name)
            if work_completed and _source_digest(path) not in recorded_sources:
                stream.append(_MissingSource(path))
            continue
        read.append(_source_digest(path))
        stream.extend(file_entries)
    return _derive_turns(stream, agent), read


async def _bind_routed_comments(session: Session, agent: AgentName) -> None:
    """Tie every delivered GitHub comment of the session to its native entry before any input is classified.

    The binding is otherwise made when the output poller next projects the session, which an agent stop does not
    wait for. Without it a person's already public comment would read as words given elsewhere and be left out.
    """
    if not session.native_log_file or not await db.get_unbound_delivered_github_inbound(session.session_id):
        return
    entries = await asyncio.to_thread(_get_entries_for_agent, session.native_log_file, agent)
    if entries:
        await bind_pending_native_turns(session, entries, agent)


async def _person_parts(session_id: str, entry: _InputEntry) -> list[TurnInputPart]:
    """Build an input entry's parts, giving a person's words the channel their binding records."""
    github_part = None
    if entry.entry_id is not None and any(segment.kind is TurnInputKind.PERSON for segment in entry.segments):
        binding = await db.get_turn_binding(binding_id_for_native_entry(session_id, entry.entry_id))
        if binding is not None:
            github_part = next((part for part in binding.parts if part.part_kind is TurnPartKind.GITHUB), None)
    parts: list[TurnInputPart] = []
    for segment in entry.segments:
        if segment.kind is TurnInputKind.PERSON:
            if github_part is not None:
                parts.append(
                    TurnInputPart(
                        TurnInputKind.PERSON,
                        segment.text,
                        channel=PersonChannel.GITHUB,
                        person_display=github_part.author.display,
                        person_login=github_part.channel_login,
                        person_link=github_part.channel_link,
                    )
                )
            else:
                parts.append(TurnInputPart(TurnInputKind.PERSON, segment.text, channel=PersonChannel.ELSEWHERE))
        else:
            parts.append(
                TurnInputPart(
                    segment.kind,
                    segment.text,
                    peer_session_id=segment.peer_session_id,
                    peer_role=segment.peer_role,
                )
            )
    return parts


def _is_completed(turn: _OpenTurn, *, is_last: bool, stopped_at: datetime | None, session_is_final: bool) -> bool:
    """A turn is completed once a later turn exists, the agent stopped at or after it, or the session is closed."""
    if not is_last or session_is_final:
        return True
    return stopped_at is not None and turn.last_time is not None and stopped_at >= turn.last_time


_default_store = SessionTurnStore(db.open_session)


async def read_completed_turns(
    session_id: str,
    after_identity: str | None = None,
    *,
    store: SessionTurnStore = _default_store,
) -> tuple[CompletedTurn, ...]:
    """Return the session's completed turns after the one identified, in order.

    A turn whose transcript can no longer be read, but which an earlier read recorded, is returned as unreadable
    with its identity and ordinal, and so is a transcript file the session's chain names that is gone though no read
    ever recorded what it held: one unreadable turn stands for its span, completed no later than the session's last
    agent stop. A file gone after a read took its turns adds nothing beyond those turns. An ``after_identity`` this
    session has no record of reads from the first turn.
    Raises ``LookupError`` when the session does not exist on this computer.
    """
    session = await db.get_session(session_id)
    if session is None:
        raise LookupError(session_id)
    agent = resolve_parser_agent(session.active_agent)
    await _bind_routed_comments(session, agent)
    chain = build_message_chain(session.transcript_files, session.native_log_file)
    derived, read_sources = await asyncio.to_thread(
        partial(
            _read_chain,
            chain,
            agent,
            work_completed=bool(session.last_agent_stop_at),
            recorded_sources=await store.known_sources(session_id),
        )
    )
    ordinals = await store.record_turns(session_id, [turn.identity for turn in derived], read_sources)
    held_ordinal = 0
    if after_identity is not None:
        held_ordinal = ordinals.get(after_identity, 0)
        if held_ordinal == 0:
            logger.warning(_UNKNOWN_HELD_TURN_EVENT, session_id=session_id)

    stopped_at = ensure_utc(session.last_agent_stop_at) if session.last_agent_stop_at else None
    session_is_final = is_session_final(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at)
    completed: list[CompletedTurn] = []
    for index, turn in enumerate(derived):
        ordinal = ordinals[turn.identity]
        if ordinal <= held_ordinal:
            continue
        if turn.source_missing:
            completed.append(
                CompletedTurn(
                    identity=turn.identity,
                    ordinal=ordinal,
                    completed_at=stopped_at,
                    input_parts=(),
                    reply="",
                    unreadable=True,
                )
            )
            continue
        if not _is_completed(
            turn, is_last=index == len(derived) - 1, stopped_at=stopped_at, session_is_final=session_is_final
        ):
            continue
        parts: list[TurnInputPart] = []
        for entry in turn.inputs:
            parts.extend(await _person_parts(session_id, entry))
        completed.append(
            CompletedTurn(
                identity=turn.identity,
                ordinal=ordinal,
                completed_at=turn.last_time,
                input_parts=tuple(parts),
                reply=_REPLY_SEPARATOR.join(turn.reply),
            )
        )
    readable = {turn.identity for turn in derived}
    completed.extend(
        CompletedTurn(identity=identity, ordinal=ordinal, completed_at=None, input_parts=(), reply="", unreadable=True)
        for identity, ordinal in ordinals.items()
        if ordinal > held_ordinal and identity not in readable
    )
    return tuple(sorted(completed, key=lambda turn: turn.ordinal))
