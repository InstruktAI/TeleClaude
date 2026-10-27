"""Bounded live event delivery, with owner-supplied recovery for current-state views."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from instrukt_ai_logging import get_logger
from redis.exceptions import ResponseError

from teleclaude.events.stream_wait import STREAM_BLOCK_MS, read_until_shutdown
from teleclaude.events.wire import EntryCodec, StreamEntry, StreamEvent

logger = get_logger(__name__)

_BATCH_SIZE = 100
_RETRY_PAUSE_S = 1.0
_INITIAL_CURSOR = "0-0"
_ID_SEPARATOR = "-"
_READER_STARTED_EVENT = "live_event_reader_started"
_READER_RECOVERING_EVENT = "live_event_reader_recovering"
_ENTRY_FAILED_EVENT = "live_event_entry_failed"
_POSITION_RETIRED_EVENT = "live_event_position_retired"
_RETIRED_GROUP_ABSENT_EVENT = "live_event_retired_group_absent"
_FEED_NAME = "shared-live-feed"

type StreamRows = list[tuple[bytes, StreamEntry]]
type StreamBatch = list[tuple[bytes, StreamRows]]
type LiveHandler = Callable[[StreamEvent], Awaitable[object]]
type SourceRecovery = Callable[[], Awaitable[None]]


class LiveStreamClient(Protocol):
    """Redis operations used by a live notification reader."""

    async def xrevrange(self, name: str, *, count: int) -> StreamRows: ...

    async def xread(self, streams: dict[str, str], *, count: int, block: int) -> StreamBatch: ...

    async def xgroup_destroy(self, name: str, groupname: str) -> object: ...


def _text(value: bytes) -> str:
    return value.decode()


def _position(value: str) -> tuple[int, int]:
    milliseconds, sequence = value.split(_ID_SEPARATOR)
    return int(milliseconds), int(sequence)


class LiveEventReader:
    """One consumer's live view of a stream: its recovery, group retirement, decoding, coalescing and handler.

    It reads nothing itself; the stream's ``SharedLiveFeed`` hands it every entry the feed reads.
    """

    def __init__(
        self,
        redis_client: LiveStreamClient,
        handler: LiveHandler,
        *,
        stream: str,
        name: str,
        retired_group: str,
        codec: EntryCodec[StreamEvent],
        recover: SourceRecovery | None = None,
        coalesce: bool = False,
    ) -> None:
        self._redis = redis_client
        self._handler = handler
        self._stream = stream
        self._name = name
        self._retired_group = retired_group
        self._codec = codec
        self._recover = recover
        self._coalesce = coalesce
        self._retired = False
        self._recovered = False

    @property
    def ready(self) -> bool:
        """Whether this view has recovered its current source and may take live entries."""
        return self._recovered

    def reset(self) -> None:
        """Require recovery before the next delivery, after the feed lost its position."""
        self._recovered = False

    async def ensure_ready(self) -> None:
        """Recover current source and retire the earlier group once, before any live entry is handled."""
        if self._recovered:
            return
        if self._recover is not None:
            await self._recover()
        if not self._retired:
            await self._retire_group()
            self._retired = True
            logger.info(_POSITION_RETIRED_EVENT, name=self._name, group=self._retired_group)
        self._recovered = True
        logger.info(_READER_STARTED_EVENT, name=self._name, stream=self._stream)

    async def recover_after_overflow(self) -> None:
        """Recover current source when the feed skipped entries it could not hand over."""
        if self._recover is not None:
            await self._recover()

    async def _retire_group(self) -> None:
        """Destroy the retired consumer group; a stream that does not exist yet holds no group to destroy."""
        try:
            await self._redis.xgroup_destroy(self._stream, self._retired_group)
        except ResponseError:
            logger.info(_RETIRED_GROUP_ABSENT_EVENT, name=self._name, stream=self._stream)

    async def deliver(self, rows: StreamRows) -> None:
        """Decode, coalesce and hand the rows to the handler, containing each entry's failure."""
        events: list[StreamEvent] = []
        for entry_id, entry in rows:
            position = _text(entry_id)
            try:
                events.append(self._codec.decode(entry, position))
            except Exception:
                logger.exception(_ENTRY_FAILED_EVENT, name=self._name, entry_id=position)
                if self._recover is not None:
                    self._recovered = False
        if self._coalesce:
            latest: dict[tuple[str, str, str | None], StreamEvent] = {}
            for event in events:
                key = (event.type, event.source, event.subject.to_token() if event.subject else None)
                latest.pop(key, None)
                latest[key] = event
            events = list(latest.values())
        for event in events:
            try:
                await self._handler(event)
            except Exception:
                logger.exception(_ENTRY_FAILED_EVENT, name=self._name, event_id=event.id)
                if self._recover is not None:
                    self._recovered = False


class SharedLiveFeed:
    """One bounded live read of a stream on one Redis, handing every entry to each live view on it.

    The stream is read once for all of its live consumers on this computer, so an entry crosses the network once.
    """

    def __init__(self, redis_client: LiveStreamClient, *, stream: str, readers: list[LiveEventReader]) -> None:
        self._redis = redis_client
        self._stream = stream
        self._readers = readers
        self._cursor: str | None = None
        self._started = False

    async def prepare_group_position(self) -> None:
        """Capture the live boundary before producers run, without creating a group."""
        if self._cursor is None:
            rows = await self._redis.xrevrange(self._stream, count=1)
            self._cursor = _text(rows[0][0]) if rows else _INITIAL_CURSOR

    async def start(self, shutdown_event: asyncio.Event) -> None:
        """Read until shutdown, recovering every view after a lost position and containing each view's failures."""
        if self._started:
            self._reset()
        self._started = True
        while not shutdown_event.is_set():
            try:
                await self.prepare_group_position()
                await self._ready_views()
                cursor = self._cursor or _INITIAL_CURSOR
                batch = await read_until_shutdown(
                    self._redis.xread({self._stream: cursor}, count=_BATCH_SIZE, block=STREAM_BLOCK_MS),
                    shutdown_event,
                )
                if batch is None:
                    return
                rows = [row for _stream, messages in batch for row in messages]
                overflowed = len(rows) >= _BATCH_SIZE
                if overflowed:
                    newest = await self._redis.xrevrange(self._stream, count=_BATCH_SIZE)
                    rows = [row for row in reversed(newest) if _position(_text(row[0])) > _position(cursor)]
                if rows:
                    self._cursor = _text(rows[-1][0])
                await self._hand_over(rows, overflowed=overflowed)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception(_READER_RECOVERING_EVENT, name=_FEED_NAME, stream=self._stream)
                self._reset()
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=_RETRY_PAUSE_S)
                except TimeoutError:
                    pass

    def _reset(self) -> None:
        self._cursor = None
        for reader in self._readers:
            reader.reset()

    async def _ready_views(self) -> None:
        for reader in self._readers:
            try:
                await reader.ensure_ready()
            except Exception:
                # A view that cannot recover now misses this batch and tries again before the next one.
                logger.exception(_READER_RECOVERING_EVENT, name=_FEED_NAME, stream=self._stream)

    async def _hand_over(self, rows: StreamRows, *, overflowed: bool) -> None:
        for reader in self._readers:
            if not reader.ready:
                continue
            try:
                if overflowed:
                    await reader.recover_after_overflow()
                await reader.deliver(rows)
            except Exception:
                logger.exception(_READER_RECOVERING_EVENT, name=_FEED_NAME, stream=self._stream)
                reader.reset()
