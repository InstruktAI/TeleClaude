"""Render and read the comments that carry a work item's conversation on GitHub.

A conversation comment opens with one envelope line that names the session, its role, the turn and when it completed,
and is followed by what the session was asked and what it answered. The envelope is the reader-facing contract and
the key a restarted publisher finds its position by; nothing in the body is ever read back.

A turn's words are written inside fenced blocks, never as markup: an agent's text names people, issues and files in
ways GitHub would turn into notifications and cross-references on a public repository.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from teleclaude.core.dates import ensure_utc
from teleclaude.core.workflow_store.github_record import (
    WORKFLOW_COMMENT_BODY_LIMIT,
    CommentEnvelopeAction,
    CommentEnvelopeField,
    render_comment_envelope,
)

_TIME_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"
_ENVELOPE_OPEN: Final = "["
_ENVELOPE_CLOSE: Final = "]"
_ENVELOPE_SEPARATOR: Final = " "
_KEY_VALUE_SEPARATOR: Final = ":"
_PART_SEPARATOR: Final = "/"
_LINE_BREAK: Final = "\n"
_BLOCK_SEPARATOR: Final = "\n\n"
_BACKTICK: Final = "`"
_MIN_FENCE: Final = 3
_FENCE_RUN_RE: Final = re.compile(r"`+")
_PIECE_LIMIT: Final = 40_000
_ENVELOPE_RESERVE: Final = 1_000
_COMMENT_BUDGET: Final = WORKFLOW_COMMENT_BODY_LIMIT - _ENVELOPE_RESERVE
_PLATFORM_LABEL: Final = "Platform"
_PEER_LABEL: Final = "Session {session_id} ({role})"
_GITHUB_LABEL: Final = "{login} on GitHub"
_GITHUB_LABEL_WITH_LINK: Final = "{login} on GitHub ([comment]({link}))"
_REPLY_LABEL: Final = "Reply"
_CONTINUED_SUFFIX: Final = " (continued)"
_LABELLED_BLOCK: Final = "**{label}**\n\n{fenced}"
_FENCED_BLOCK: Final = "{fence}\n{text}\n{fence}"
_PERSON_ELSEWHERE_NOTE: Final = "_A person spoke to this session outside GitHub._"
_NO_REPLY_NOTE: Final = "_The session gave no reply._"


class TurnState(StrEnum):
    """What a turn's comments show of its content."""

    COMPLETE = "complete"
    WITHHELD = "withheld"
    UNAVAILABLE = "unavailable"


class TurnBlockKind(StrEnum):
    """Who authored one block of a turn's comment."""

    PLATFORM = "platform"
    PEER = "peer"
    GITHUB_PERSON = "github_person"
    PERSON_ELSEWHERE = "person_elsewhere"
    REPLY = "reply"


@dataclass(frozen=True)
class TurnBlock:
    """One authored block of a turn: an input part or the reply, its text already protected."""

    kind: TurnBlockKind
    text: str = ""
    peer_session_id: str | None = None
    peer_role: str | None = None
    login: str | None = None
    link: str | None = None


@dataclass(frozen=True)
class TurnEnvelope:
    """The facts a turn comment's opening line carries."""

    session_id: str
    role: str
    ordinal: int
    completed_at: datetime
    state: TurnState
    part: int
    parts: int


def format_envelope_time(moment: datetime) -> str:
    """Render an instant the way the conversation's envelopes carry it."""
    return ensure_utc(moment).strftime(_TIME_FORMAT)


def render_conversation_start(moment: datetime) -> str:
    """Render the ledger entry that records when the project's conversation began."""
    return render_comment_envelope(
        (
            (CommentEnvelopeField.ACTION, CommentEnvelopeAction.CONVERSATION_START),
            (CommentEnvelopeField.AT, format_envelope_time(moment)),
        )
    )


def parse_conversation_start(body: str) -> datetime | None:
    """Read the moment a conversation-start entry records; None for any other comment."""
    fields = _envelope_fields(body)
    if fields.get(CommentEnvelopeField.ACTION) != CommentEnvelopeAction.CONVERSATION_START:
        return None
    return _parse_time(fields.get(CommentEnvelopeField.AT))


def render_turn_comments(
    session_id: str,
    role: str,
    ordinal: int,
    completed_at: datetime,
    state: TurnState,
    blocks: Sequence[TurnBlock],
) -> tuple[str, ...]:
    """Render one turn as the comments that carry it, a long turn continuing in the comments that follow.

    A withheld or unavailable turn is its envelope alone: none of its content is written.
    """
    if state is not TurnState.COMPLETE:
        return (_envelope(session_id, role, ordinal, completed_at, state, part=1, parts=1),)
    groups = _pack(_pieces(blocks))
    total = len(groups)
    return tuple(
        _envelope(session_id, role, ordinal, completed_at, state, part=index, parts=total)
        + _BLOCK_SEPARATOR
        + _BLOCK_SEPARATOR.join(group)
        for index, group in enumerate(groups, start=1)
    )


def parse_turn_envelope(body: str) -> TurnEnvelope | None:
    """Read the opening line of a turn comment; None when the comment does not open as one."""
    fields = _envelope_fields(body)
    if fields.get(CommentEnvelopeField.ACTION) != CommentEnvelopeAction.TURN:
        return None
    session_id = fields.get(CommentEnvelopeField.SESSION)
    role = fields.get(CommentEnvelopeField.ROLE)
    ordinal = fields.get(CommentEnvelopeField.TURN)
    completed_at = _parse_time(fields.get(CommentEnvelopeField.AT))
    if not session_id or not role or ordinal is None or not ordinal.isascii() or not ordinal.isdecimal():
        return None
    if completed_at is None:
        return None
    part, parts = _parse_part(fields.get(CommentEnvelopeField.PART))
    state = TurnState.COMPLETE
    if CommentEnvelopeField.WITHHELD in fields:
        state = TurnState.WITHHELD
    elif CommentEnvelopeField.UNAVAILABLE in fields:
        state = TurnState.UNAVAILABLE
    return TurnEnvelope(
        session_id=session_id,
        role=role,
        ordinal=int(ordinal),
        completed_at=completed_at,
        state=state,
        part=part,
        parts=parts,
    )


def _envelope(
    session_id: str,
    role: str,
    ordinal: int,
    completed_at: datetime,
    state: TurnState,
    *,
    part: int,
    parts: int,
) -> str:
    return render_comment_envelope(
        (
            (CommentEnvelopeField.SESSION, session_id),
            (CommentEnvelopeField.ROLE, role),
            (CommentEnvelopeField.ACTION, CommentEnvelopeAction.TURN),
            (CommentEnvelopeField.TURN, ordinal),
            (CommentEnvelopeField.AT, format_envelope_time(completed_at)),
            (CommentEnvelopeField.WITHHELD, state is TurnState.WITHHELD),
            (CommentEnvelopeField.UNAVAILABLE, state is TurnState.UNAVAILABLE),
            (CommentEnvelopeField.PART, f"{part}{_PART_SEPARATOR}{parts}" if parts > 1 else None),
        )
    )


def _label(block: TurnBlock) -> str | None:
    """The line that names who wrote a block; None for a block that is only a note."""
    match block.kind:
        case TurnBlockKind.PLATFORM:
            return _PLATFORM_LABEL
        case TurnBlockKind.PEER:
            return _PEER_LABEL.format(session_id=block.peer_session_id, role=block.peer_role)
        case TurnBlockKind.GITHUB_PERSON:
            if block.link:
                return _GITHUB_LABEL_WITH_LINK.format(login=block.login, link=block.link)
            return _GITHUB_LABEL.format(login=block.login)
        case TurnBlockKind.REPLY:
            return _REPLY_LABEL
        case TurnBlockKind.PERSON_ELSEWHERE:
            return None


def _pieces(blocks: Sequence[TurnBlock]) -> Iterator[str]:
    """Each block as the rendered pieces that fit one comment, long text cut at line ends."""
    for block in blocks:
        label = _label(block)
        if label is None:
            yield _PERSON_ELSEWHERE_NOTE
        elif not block.text:
            yield (
                _NO_REPLY_NOTE
                if block.kind is TurnBlockKind.REPLY
                else _LABELLED_BLOCK.format(label=label, fenced=_fenced(block.text))
            )
        else:
            for index, text in enumerate(_cut(block.text)):
                shown = label if index == 0 else label + _CONTINUED_SUFFIX
                yield _LABELLED_BLOCK.format(label=shown, fenced=_fenced(text))


def _pack(pieces: Iterator[str]) -> list[list[str]]:
    """Group rendered pieces into comments, each within the body limit; every turn has at least one."""
    groups: list[list[str]] = [[]]
    size = 0
    for piece in pieces:
        cost = len(piece) + len(_BLOCK_SEPARATOR)
        if groups[-1] and size + cost > _COMMENT_BUDGET:
            groups.append([])
            size = 0
        groups[-1].append(piece)
        size += cost
    return groups


def _cut(text: str) -> Iterator[str]:
    """Cut text into pieces that join back to it, preferring line ends."""
    start = 0
    while start < len(text):
        end = min(start + _PIECE_LIMIT, len(text))
        if end < len(text):
            line_end = text.rfind(_LINE_BREAK, start, end)
            end = line_end + 1 if line_end > start else end
        yield text[start:end]
        start = end


def _fenced(text: str) -> str:
    """Wrap text in a code fence longer than any run of backticks it holds, so it cannot end the fence."""
    longest = max((len(run) for run in _FENCE_RUN_RE.findall(text)), default=0)
    fence = _BACKTICK * max(_MIN_FENCE, longest + 1)
    return _FENCED_BLOCK.format(fence=fence, text=text)


def _envelope_fields(body: str) -> dict[str, str]:
    """Read the key:value fields of a comment's opening line; a bare field reads as present with no value."""
    line = body.split(_LINE_BREAK, 1)[0].strip()
    if not (line.startswith(_ENVELOPE_OPEN) and line.endswith(_ENVELOPE_CLOSE)):
        return {}
    fields: dict[str, str] = {}
    for token in line[1:-1].split(_ENVELOPE_SEPARATOR):
        key, _, value = token.partition(_KEY_VALUE_SEPARATOR)
        fields[key] = value
    return fields


def _parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, _TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_part(value: str | None) -> tuple[int, int]:
    if value is None:
        return 1, 1
    index, _, total = value.partition(_PART_SEPARATOR)
    if index.isascii() and index.isdecimal() and total.isascii() and total.isdecimal():
        return int(index), int(total)
    return 1, 1
