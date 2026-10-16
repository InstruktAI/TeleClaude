"""The retained workflow event trail of one item: a bounded, cursor-paged read of the platform event stream.

``local/projects/teleclaude/spec/feature/event-catalog/item-event-occurrences``. The view reads the platform stream this
computer emitted into and keeps only the occurrences of the five workflow kinds whose recorded source computer,
project home and subject are the selection. A logical occurrence takes the position of its first retained copy in the
read snapshot, whatever precedes a cursor; later copies add nothing. Reach is applied to every occurrence on every
read, and counts, pages and coverage are computed over the occurrences the caller may see. A cursor pins a position
and a retained boundary, never an authority.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Protocol

from teleclaude.core.models import JsonDict, JsonValue
from teleclaude.events.envelope import home_owner_token, home_token
from teleclaude.events.stream_reader import STREAM_ID_SEPARATOR, StreamUnavailable
from teleclaude.events.wire import StreamEntry, StreamEvent, decode
from teleclaude.identity_reach import Reach
from teleclaude.paths import STATE_DIR

TRAIL_EVENT_TYPES: Final = frozenset(
    {
        "sdlc.todo.head_advanced",
        "sdlc.todo.claim_changed",
        "sdlc.todo.waiting",
        "sdlc.todo.ready",
        "sdlc.todo.phase_advanced",
    }
)
TODO_SUBJECT_PREFIX: Final = "todo:"
DEFAULT_LIMIT: Final = 50
MAXIMUM_LIMIT: Final = 200
SCAN_CHUNK: Final = 1000
SCAN_ATTEMPTS: Final = 3
CURSOR_VERSION: Final = 2
CURSOR_KEY_FILE: Final = "event-trail-cursor.key"
CURSOR_KEY_BYTES: Final = 32
CURSOR_KEY_MODE: Final = 0o600
NO_POSITION: Final = "0-0"

LIMIT_PRUNED: Final = "history_pruned_from_interval"
LIMIT_COMPUTER_LOCAL: Final = "computer_local"
LIMIT_UNDECODABLE: Final = "undecodable_entries"
LIMIT_RETAINED_ONLY: Final = "retained_only"

UNAVAILABLE: Final = "event_platform_unavailable"
CURSOR_INVALID: Final = "cursor_invalid"
CURSOR_LOST: Final = "cursor_lost"


class TrailError(Exception):
    """A read that establishes nothing, with the cause that distinguishes it from an empty covered interval."""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


class StreamReader(Protocol):
    """The retained stream, read in append order by stream position."""

    async def oldest(self) -> str | None:
        """The oldest retained position, or None when nothing is retained."""
        ...

    async def newest(self) -> str | None:
        """The newest position, or None when nothing is retained."""
        ...

    async def entries(self, after: str | None, through: str, count: int) -> list[tuple[str, StreamEntry]]:
        """Up to ``count`` entries with a position after ``after`` (exclusive) and up to ``through`` (inclusive)."""
        ...

    async def length(self) -> int:
        """How many entries are retained."""
        ...

    @property
    def capacity(self) -> int:
        """The length at which the stream starts trimming its oldest entries."""
        ...


@dataclass(frozen=True)
class Selection:
    """What identifies one item\'s trail: the emitting computer, the project home and the item subject."""

    computer: str
    home: str
    subject: str

    def digest(self) -> str:
        return hashlib.sha256("\x1f".join((self.computer, self.home, self.subject)).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class TrailRequest:
    """One read: a mark, a read after an observation cursor, a continuation, or the whole retained window."""

    limit: int = DEFAULT_LIMIT
    mark: bool = False
    since: str | None = None
    cursor: str | None = None


class CursorSeal:
    """Seals a cursor so its holder can neither read the stream positions inside it nor forge another.

    The cursor carries a watermark of the whole stream, which the caller\'s reach does not admit. It is sealed with a
    key only the daemon holds: a stream cipher built from HMAC-SHA256 and a message authentication code over the result.
    """

    NONCE_BYTES: Final = 12
    MAC_BYTES: Final = 16
    BLOCK_BYTES: Final = 32

    def __init__(self, key: bytes) -> None:
        self._key = key

    def _keystream(self, nonce: bytes, length: int) -> bytes:
        blocks = (
            hmac.new(self._key, b"enc" + nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
            for counter in range(-(-length // self.BLOCK_BYTES))
        )
        return b"".join(blocks)[:length]

    def seal(self, body: bytes) -> str:
        nonce = secrets.token_bytes(self.NONCE_BYTES)
        cipher = bytes(left ^ right for left, right in zip(body, self._keystream(nonce, len(body)), strict=True))
        mac = hmac.new(self._key, b"mac" + nonce + cipher, hashlib.sha256).digest()[: self.MAC_BYTES]
        return base64.urlsafe_b64encode(nonce + cipher + mac).decode()

    def open(self, token: str) -> bytes:
        raw = base64.urlsafe_b64decode(token.encode())
        if len(raw) < self.NONCE_BYTES + self.MAC_BYTES:
            raise ValueError("too short")
        nonce, cipher, mac = raw[: self.NONCE_BYTES], raw[self.NONCE_BYTES : -self.MAC_BYTES], raw[-self.MAC_BYTES :]
        expected = hmac.new(self._key, b"mac" + nonce + cipher, hashlib.sha256).digest()[: self.MAC_BYTES]
        if not hmac.compare_digest(mac, expected):
            raise ValueError("not sealed by this daemon")
        return bytes(left ^ right for left, right in zip(cipher, self._keystream(nonce, len(cipher)), strict=True))


def daemon_seal() -> CursorSeal:
    """The seal of this daemon: a random key kept in its state directory, created on first use."""
    path = STATE_DIR / CURSOR_KEY_FILE
    try:
        key = path.read_bytes()
    except FileNotFoundError:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(CURSOR_KEY_BYTES)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, CURSOR_KEY_MODE)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(key)
    return CursorSeal(key)


@dataclass(frozen=True)
class Cursor:
    """A pinned position in the caller\'s own view of the stream, never a position the caller can read of a hidden one.

    ``anchor`` and ``anchor_id`` name the last admitted entry the read consumed (or none), ``floor`` the oldest admitted
    entry retained when the cursor was captured, ``end`` the admitted entry a paged read is pinned to, and
    ``watermark`` the newest entry of the whole stream when the interval began (none for an empty stream): an interval
    whose entries after the watermark may have been trimmed is reported incomplete even when none of them was visible.
    The cursor is sealed, so none of these positions is readable by its holder.
    """

    selection: str
    anchor: str
    anchor_id: str
    floor: str
    watermark: str
    end: str | None = None

    def encode(self, seal: CursorSeal) -> str:
        body = {
            "v": CURSOR_VERSION,
            "s": self.selection,
            "p": self.anchor,
            "i": self.anchor_id,
            "f": self.floor,
            "w": self.watermark,
            "e": self.end,
        }
        return seal.seal(json.dumps(body, separators=(",", ":")).encode())

    @classmethod
    def decode(cls, value: str, selection: Selection, seal: CursorSeal) -> Cursor:
        try:
            body = json.loads(seal.open(value))
            parsed = cls(
                selection=str(body["s"]),
                anchor=_stream_id(str(body["p"])),
                anchor_id=str(body["i"]),
                floor=_stream_id(str(body["f"])),
                watermark=_stream_id(str(body["w"])),
                end=_stream_id(str(body["e"])) if body["e"] is not None else None,
            )
            version = body["v"]
        except (binascii.Error, ValueError, KeyError, TypeError) as error:
            raise TrailError(CURSOR_INVALID, "the cursor cannot be read") from error
        if version != CURSOR_VERSION or parsed.selection != selection.digest():
            raise TrailError(CURSOR_INVALID, "the cursor belongs to another selection or version")
        return parsed


@dataclass(frozen=True)
class Occurrence:
    """One logical occurrence: the envelope of its first retained copy, at that copy\'s position."""

    position: str
    event: StreamEvent

    def to_json(self) -> JsonDict:
        event = self.event
        related: list[JsonValue] = [reference.to_token() for reference in event.related]
        return {
            "position": self.position,
            "id": event.id,
            "type": event.type,
            "time": event.time.isoformat(),
            "source": {
                "computer": event.source,
                "origin": home_token(event.home),
                "owner": home_owner_token(event.home_owner),
            },
            "subject": event.subject.to_token() if event.subject is not None else None,
            "data": event.data,
            "related": related,
            "causationid": event.causationid,
        }


@dataclass
class TrailResult:
    """What a read establishes: visible occurrences, the covered interval and what remains."""

    selection: Selection
    occurrences: list[Occurrence] = field(default_factory=list)
    retained_from: str | None = None
    retained_to: str | None = None
    complete: bool = True
    limits: list[str] = field(default_factory=list)
    next_cursor: str | None = None
    observation_cursor: str | None = None

    def to_json(self) -> JsonDict:
        coverage: JsonDict = {
            "retained_only": True,
            "retained_from": self.retained_from,
            "retained_from_time": _stream_time(self.retained_from),
            "retained_to": self.retained_to,
            "retained_to_time": _stream_time(self.retained_to),
            "complete": self.complete,
            "limits": list(self.limits),
        }
        result: JsonDict = {
            "item": {
                "subject": self.selection.subject,
                "project": self.selection.home,
                "computer": self.selection.computer,
            },
            "occurrences": [occurrence.to_json() for occurrence in self.occurrences],
            "coverage": coverage,
            "continuation": {"cursor": self.next_cursor, "remains": self.next_cursor is not None},
        }
        if self.observation_cursor is not None:
            result["observation_cursor"] = self.observation_cursor
        return result


def _stream_id(value: str) -> str:
    """A stream position as given, refused when it is not a millisecond-sequence pair."""
    millis, separator, sequence = value.partition(STREAM_ID_SEPARATOR)
    if not separator or not millis.isdigit() or not sequence.isdigit():
        raise ValueError(value)
    return value


def _key(position: str) -> tuple[int, int]:
    millis, _, sequence = position.partition(STREAM_ID_SEPARATOR)
    return int(millis), int(sequence)


def _stream_time(position: str | None) -> str | None:
    if position is None:
        return None
    return datetime.fromtimestamp(_key(position)[0] / 1000, tz=UTC).isoformat()


def selects(event: StreamEvent, selection: Selection) -> bool:
    """Whether an event is one of the five kinds, emitted here, in the selected project, about the selected item."""
    return (
        event.type in TRAIL_EVENT_TYPES
        and event.source == selection.computer
        and home_token(event.home) == selection.home
        and event.subject is not None
        and event.subject.to_token() == selection.subject
    )


@dataclass
class _Snapshot:
    """What one stable pass over the retained stream read, as the caller\'s reach admits it."""

    first_position: str | None = None  # the first retained entry read; internal, never published
    admitted: list[tuple[str, str]] = field(default_factory=list)
    occurrences: list[Occurrence] = field(default_factory=list)
    undecodable: int = 0


class _Unstable(Exception):
    """The stream was trimmed past entries not yet read: the pass proves nothing about the interval it claims."""


async def _pass(reader: StreamReader, selection: Selection, reach: Reach, through: str) -> _Snapshot:
    """Read the retained stream up to ``through`` in order, keeping what the reach admits and the selected first copies."""
    snapshot = _Snapshot()
    first_copy: set[str] = set()
    after: str | None = None
    while True:
        resumed_from = after
        chunk = await reader.entries(after, through, SCAN_CHUNK)
        if resumed_from is not None:
            oldest = await reader.oldest()
            if oldest is not None and _key(oldest) > _key(resumed_from):
                raise _Unstable  # entries after the last one read, before this chunk, were trimmed unread
        if not chunk:
            break
        if snapshot.first_position is None:
            snapshot.first_position = chunk[0][0]
        for position, entry in chunk:
            try:
                event = decode(entry, position)
            except (KeyError, ValueError, TypeError):
                snapshot.undecodable += 1
                continue
            if not reach.admits(home_token(event.home), home_owner_token(event.home_owner), None):
                continue
            snapshot.admitted.append((position, event.id))
            if selects(event, selection) and event.id not in first_copy:
                first_copy.add(event.id)
                snapshot.occurrences.append(Occurrence(position, event))
        after = chunk[-1][0]
        if len(chunk) < SCAN_CHUNK:
            break
    return snapshot


async def _stable_pass(reader: StreamReader, selection: Selection, reach: Reach, through: str) -> _Snapshot:
    for _ in range(SCAN_ATTEMPTS):
        try:
            return await _pass(reader, selection, reach, through)
        except _Unstable:
            continue
        except StreamUnavailable as error:
            raise TrailError(UNAVAILABLE, str(error)) from error
    raise TrailError(UNAVAILABLE, "the retained stream was trimmed faster than it could be read")


def _ordering_holds(cursor: Cursor, snapshot: _Snapshot) -> bool:
    """Whether the evidence that fixes the cursor\'s logical ordering is still retained.

    The entry the cursor stopped at must still be there, and nothing the caller can see may have been trimmed since the
    cursor was captured: otherwise a later copy of an occurrence whose first copy is gone could take its place.
    """
    if cursor.anchor == NO_POSITION:
        return True
    if (cursor.anchor, cursor.anchor_id) not in snapshot.admitted:
        return False
    return bool(snapshot.admitted) and _key(snapshot.admitted[0][0]) <= _key(cursor.floor)


def _cursor_from(
    selection: Selection, last: tuple[str, str] | None, floor: str, watermark: str, end: str | None
) -> Cursor:
    position, event_id = last if last is not None else (NO_POSITION, "")
    return Cursor(selection.digest(), position, event_id, floor, watermark, end)


async def _possibly_trimmed_since(reader: StreamReader, cursor: Cursor, snapshot: _Snapshot) -> bool:
    """Whether entries emitted after the cursor\'s watermark may have left the retained stream, visible or not.

    With a watermark, entries after it are lost exactly when the oldest retained entry is newer than it. A cursor taken
    of an empty stream has no watermark; trimming can only have happened if the stream has since reached its capacity.
    """
    if cursor.watermark != NO_POSITION:
        return snapshot.first_position is not None and _key(snapshot.first_position) > _key(cursor.watermark)
    return await reader.length() >= reader.capacity


async def read_trail(
    reader: StreamReader, selection: Selection, reach: Reach, request: TrailRequest, seal: CursorSeal
) -> TrailResult:
    """Read one page (or a mark) of an item\'s trail; raises TrailError for the reads that establish nothing.

    Every position, bound and count published is derived from the entries the caller\'s reach admits, so records the
    caller may not see neither appear in nor move any part of the result; the stream positions a cursor must keep to
    detect their loss travel sealed inside it.
    """
    limit = min(max(request.limit, 1), MAXIMUM_LIMIT)
    cursor = None
    if request.cursor is not None:
        cursor = Cursor.decode(request.cursor, selection, seal)
        if cursor.end is None:
            raise TrailError(CURSOR_INVALID, "a mark cannot continue a read; pass it as --since")
    elif request.since is not None:
        cursor = Cursor.decode(request.since, selection, seal)
    try:
        newest = await reader.newest()
    except StreamUnavailable as error:
        raise TrailError(UNAVAILABLE, str(error)) from error
    through = cursor.end if cursor is not None and cursor.end is not None else newest
    snapshot = await _stable_pass(reader, selection, reach, through) if through is not None else _Snapshot()
    if cursor is not None and (
        snapshot.first_position is None or (cursor.end and _key(snapshot.first_position) > _key(cursor.end))
    ):
        raise TrailError(CURSOR_LOST, "everything the cursor covered has been trimmed from the retained stream")
    first = snapshot.admitted[0][0] if snapshot.admitted else None
    last = snapshot.admitted[-1] if snapshot.admitted else None
    result = TrailResult(selection, retained_from=first, retained_to=last[0] if last is not None else None)
    result.limits.extend((LIMIT_RETAINED_ONLY, LIMIT_COMPUTER_LOCAL))
    if snapshot.undecodable and reach.everything:
        result.limits.append(f"{LIMIT_UNDECODABLE}:{snapshot.undecodable}")
    floor = first or NO_POSITION
    watermark = cursor.watermark if cursor is not None else (newest or NO_POSITION)
    if request.mark:
        result.observation_cursor = _cursor_from(selection, last, floor, newest or NO_POSITION, None).encode(seal)
        return result
    if cursor is None:
        shown = snapshot.occurrences
    else:
        try:
            trimmed = await _possibly_trimmed_since(reader, cursor, snapshot)
        except StreamUnavailable as error:
            raise TrailError(UNAVAILABLE, str(error)) from error
        if trimmed or not _ordering_holds(cursor, snapshot):
            result.complete = False
            result.limits.append(LIMIT_PRUNED)
            return result
        floor = cursor.floor
        shown = [o for o in snapshot.occurrences if _key(o.position) > _key(cursor.anchor)]
    result.occurrences = shown[:limit]
    if len(shown) > limit:
        tail = result.occurrences[-1]
        end = cursor.end if cursor is not None and cursor.end is not None else (last[0] if last is not None else None)
        result.next_cursor = _cursor_from(selection, (tail.position, tail.event.id), floor, watermark, end).encode(seal)
    return result
