"""Bounded live event delivery, with owner-supplied recovery for current-state views."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from instrukt_ai_logging import get_logger

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
    """Read a bounded live window without a pending ledger or historical replay."""

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
        self._cursor: str | None = None
        self._started = False
        self._retired = False
        self._recovered = False

    async def prepare_group_position(self) -> None:
        """Capture the live boundary before producers run, without creating a group."""
        if self._cursor is None:
            rows = await self._redis.xrevrange(self._stream, count=1)
            self._cursor = _text(rows[0][0]) if rows else _INITIAL_CURSOR

    async def start(self, shutdown_event: asyncio.Event) -> None:
        """Recover current source on connection loss and contain individual presentation failures."""
        if self._started:
            self._cursor = None
            self._recovered = False
        self._started = True
        while not shutdown_event.is_set():
            try:
                await self.prepare_group_position()
                if not self._recovered:
                    if self._recover is not None:
                        await self._recover()
                    if not self._retired:
                        await self._redis.xgroup_destroy(self._stream, self._retired_group)
                        self._retired = True
                        logger.info(_POSITION_RETIRED_EVENT, name=self._name, group=self._retired_group)
                    self._recovered = True
                    logger.info(_READER_STARTED_EVENT, name=self._name, stream=self._stream)
                cursor = self._cursor or _INITIAL_CURSOR
                batch = await read_until_shutdown(
                    self._redis.xread({self._stream: cursor}, count=_BATCH_SIZE, block=STREAM_BLOCK_MS),
                    shutdown_event,
                )
                if batch is None:
                    return
                rows = [row for _stream, messages in batch for row in messages]
                if len(rows) >= _BATCH_SIZE:
                    newest = await self._redis.xrevrange(self._stream, count=_BATCH_SIZE)
                    rows = [row for row in reversed(newest) if _position(_text(row[0])) > _position(cursor)]
                    if self._recover is not None:
                        await self._recover()
                await self._deliver(rows)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception(_READER_RECOVERING_EVENT, name=self._name, stream=self._stream)
                self._cursor = None
                self._recovered = False
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=_RETRY_PAUSE_S)
                except TimeoutError:
                    pass

    async def _deliver(self, rows: StreamRows) -> None:
        events: list[StreamEvent] = []
        for entry_id, entry in rows:
            self._cursor = _text(entry_id)
            try:
                events.append(self._codec.decode(entry, self._cursor))
            except Exception:
                logger.exception(_ENTRY_FAILED_EVENT, name=self._name, entry_id=self._cursor)
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
