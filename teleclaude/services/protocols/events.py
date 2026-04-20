"""Event channel primitives — durable outbox with per-subscriber cursors and LISTEN/NOTIFY.

Architecture:
    State services emit events into channel outbox tables as part of their write
    transactions. Each channel has independent subscriber cursors. Postgres
    LISTEN/NOTIFY wakes subscribers immediately; cursors provide crash recovery.

    ┌─────────────┐     ┌──────────────┐     ┌────────────────┐
    │   Service   │────▶│ Outbox Table │────▶│  Subscribers   │
    │ (emit in tx)│     │ (per channel)│     │ (cursor-based) │
    └─────────────┘     └──────────────┘     └────────────────┘
                              │
                         NOTIFY fires
                         automatically
                         via trigger
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class Channel(StrEnum):
    """Named event channels — one outbox table and consumer loop per channel."""

    HOOKS = "hooks"
    LIFECYCLE = "lifecycle"
    WORK = "work"


# guard: loose-dict-func - v2 event payload, schema TBD per channel
@dataclass(frozen=True)
class EventEnvelope:
    """Immutable event record as stored in the outbox."""

    id: int
    channel: Channel
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


type EventHandler = Callable[[EventEnvelope], Awaitable[None]]


@dataclass
class Subscriber:
    """A named consumer with its own cursor position in a channel."""

    name: str
    channel: Channel
    handler: EventHandler
    cursor: int = 0


# guard: loose-dict-func - v2 protocol stub, payload schema TBD
class EventEmitter(Protocol):
    """Write-side: emit events into a channel's outbox within a transaction."""

    async def emit(
        self,
        channel: Channel,
        event_type: str,
        payload: dict[str, Any],
        *,
        connection: Any = None,
    ) -> int:
        """Write event to outbox table.

        When ``connection`` is provided, the event is written within that
        transaction — guaranteeing atomicity with the state change that
        produced it. Returns the event ID.
        """
        ...


class EventConsumer(Protocol):
    """Read-side: subscribe to channels and process events via cursors."""

    def subscribe(self, subscriber: Subscriber) -> None:
        """Register a subscriber on a channel.

        The subscriber's cursor is persisted in the database. On first
        registration, the cursor starts at the current position (no
        backfill). The subscriber's handler is called for each new event.
        """
        ...

    async def run_channel(self, channel: Channel) -> None:
        """Run the consumer loop for one channel.

        Reads pending events for each subscriber (after their cursor),
        calls handlers, advances cursors on success. Subscribers within
        a channel are processed concurrently via asyncio.gather.

        In Postgres mode, this loop blocks on LISTEN and wakes on NOTIFY.
        On startup, it reads from cursors first to catch up on missed events.
        """
        ...

    async def prune(self, channel: Channel) -> int:
        """Delete events consumed by all subscribers.

        Removes events where id < MIN(cursor) across all subscribers
        on the channel. Returns the number of pruned rows.
        """
        ...


class EventChannelService(EventEmitter, EventConsumer, Protocol):
    """Combined read/write event channel service.

    One instance manages all channels. Each channel has:
    - Its own outbox table (or partition)
    - Its own subscriber cursors
    - Its own independent consumer loop
    - Postgres LISTEN/NOTIFY for instant wakeup
    """

    async def initialize(self) -> None:
        """Create outbox and cursor tables if they don't exist."""
        ...

    async def run(self) -> None:
        """Start all channel consumer loops concurrently.

        Each channel runs its own independent loop via asyncio.gather.
        Loops never exit — they block on LISTEN between processing batches.
        """
        ...

    async def shutdown(self) -> None:
        """Stop all consumer loops and flush pending cursor advances."""
        ...
