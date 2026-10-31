"""Event consumers: independent reactions to platform events, each with its own progress through the stream.

A consumer declares its interest, handler and delivery lifetime. Retained reactions keep independent
consumer groups and handled-event records. Live reactions use a bounded in-memory cursor and their
owner's source recovery, without historical replay or a pending ledger. Selection reads only event
attributes, and handlers receive the event rather than its transport state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from instrukt_ai_logging import get_logger

from teleclaude.events.db import EventDB
from teleclaude.events.envelope import EventHomeKind, EventHomeRef, ReceivedEvent
from teleclaude.events.live_reader import LiveEventReader, LiveStreamClient, SharedLiveFeed, SourceRecovery
from teleclaude.events.processor import STREAM_NAME, EventProcessor
from teleclaude.events.redis_reachability import RedisReachability, is_redis_unreachable
from teleclaude.events.references import ReferenceKind
from teleclaude.events.scope import EventScope, ScopedClients, scopes_of_interest
from teleclaude.events.type_pattern import TypePattern
from teleclaude.events.wire import PLATFORM_ENTRY_CODEC, EntryCodec, StreamEvent

if TYPE_CHECKING:
    from teleclaude.core.task_registry import SupervisedTask, TaskRegistry

logger = get_logger(__name__)

#: How long a computer keeps its record that a consumer handled an event; duplicate protection lasts this long.
HANDLED_RECORD_RETENTION = timedelta(days=7)

type EventHandler = Callable[[ReceivedEvent], Awaitable[None]]

_GROUP_TEMPLATE = "consumer-{name}-{computer}"
_READER_TEMPLATE = "{name}-{computer}"
_NO_TYPES_ERROR = "a consumer's interest names at least one event type pattern"
_NO_NAME_ERROR = "a consumer is declared with a name"
_DUPLICATE_NAMES_ERROR = "consumer names must be unique on a computer; declared more than once: {names}"
_NAME_SEPARATOR = ", "
_CONSUMER_STARTED_EVENT = "Event consumer starting"
_RECOVERY_REQUIRES_LIVE_ERROR = "Source recovery and coalescing belong to live consumers"
_CONSUMER_TASK_TEMPLATE = "event-consumer-{name}"
_SCOPED_NAME_TEMPLATE = "{name}@{scope}"
_LIVE_FEED_NAME = "live-feed"


class ConsumerDelivery(StrEnum):
    """The consuming owner's need for occurrence replay or current live notification."""

    RETAINED = "retained"
    LIVE = "live"


def consumer_group_name(name: str, computer: str) -> str:
    """Return the stable Redis group for a named consumer on one computer."""
    return _GROUP_TEMPLATE.format(name=name, computer=computer)


def consumer_reader_name(name: str, computer: str) -> str:
    """Return the stable reader identity that owns ordered pending recovery."""
    return _READER_TEMPLATE.format(name=name, computer=computer)


@dataclass(frozen=True)
class Interest:
    """The events a consumer is handed, declared on event attributes only: type, source, subject and origin."""

    types: tuple[TypePattern, ...]
    own_computer_only: bool = False
    subject_kinds: frozenset[ReferenceKind] = frozenset()
    origin_kinds: frozenset[EventHomeKind] = frozenset()

    def __post_init__(self) -> None:
        if not self.types:
            raise ValueError(_NO_TYPES_ERROR)

    def selects(self, event: ReceivedEvent, computer: str) -> bool:
        """Whether the event is within this interest; reads the event's type, source, subject and origin only."""
        if not any(pattern.matches(event.type) for pattern in self.types):
            return False
        if self.own_computer_only and event.source != computer:
            return False
        if self.subject_kinds and (
            event.subject is None or not any(event.subject.is_kind(kind) for kind in self.subject_kinds)
        ):
            return False
        # The delivered `home` attribute is the event's origin: the registered project, person or company it happened in.
        origin = event.home
        return not self.origin_kinds or (isinstance(origin, EventHomeRef) and origin.kind in self.origin_kinds)


@dataclass(frozen=True)
class Consumer:
    """One reaction to platform events on one computer: its name, its interest, and the handler it runs."""

    name: str
    interest: Interest
    handler: EventHandler
    delivery: ConsumerDelivery = ConsumerDelivery.RETAINED
    recover: SourceRecovery | None = None
    coalesce: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError(_NO_NAME_ERROR)
        if self.delivery is ConsumerDelivery.RETAINED and (self.recover is not None or self.coalesce):
            raise ValueError(_RECOVERY_REQUIRES_LIVE_ERROR)


def _received(event: StreamEvent) -> ReceivedEvent:
    """The event as every reader sees it, without the notification path's legacy facts."""
    return ReceivedEvent.model_validate({name: getattr(event, name) for name in ReceivedEvent.model_fields})


class _ConsumerPipeline:
    """The stream-entry pipeline of one consumer: select, skip a handled repeat, hand over, then record."""

    def __init__(self, consumer: Consumer, db: EventDB, computer: str) -> None:
        self._consumer = consumer
        self._db = db
        self._computer = computer
        # A consumer that reads two scopes' Redis has a reader on each; its reaction still handles one event at a time.
        self._serial = asyncio.Lock()

    async def execute(self, event: StreamEvent, /) -> None:
        """Apply interest and delivery lifetime before invoking the owning reaction."""
        async with self._serial:
            await self._execute(event)

    async def _execute(self, event: StreamEvent) -> None:
        consumer = self._consumer
        if not consumer.interest.selects(event, self._computer):
            return
        if consumer.delivery is ConsumerDelivery.LIVE:
            await consumer.handler(_received(event))
            return
        if await self._db.has_handled_event(consumer.name, event.id):
            return
        await consumer.handler(_received(event))
        await self._db.record_handled_event(consumer.name, event.id, datetime.now(UTC))


def _live_view(
    consumer: Consumer,
    pipeline: _ConsumerPipeline,
    redis_client: Any,
    computer: str,
    stream: str,
    codec: EntryCodec[StreamEvent],
) -> LiveEventReader:
    """One live consumer's view of a stream, fed by the stream's shared live feed on that Redis."""
    return LiveEventReader(
        cast(LiveStreamClient, redis_client),
        pipeline.execute,
        stream=stream,
        name=consumer.name,
        retired_group=consumer_group_name(consumer.name, computer),
        codec=codec,
        recover=consumer.recover,
        coalesce=consumer.coalesce,
    )


def _retained_reader(
    consumer: Consumer,
    pipeline: _ConsumerPipeline,
    redis_client: Any,
    computer: str,
    stream: str,
    codec: EntryCodec[StreamEvent],
) -> EventProcessor[StreamEvent]:
    """The consumer group reader that hands one Redis's entries of a stream to one retained consumer."""
    return EventProcessor(
        redis_client,
        pipeline,
        codec=codec,
        declared_name=consumer.name,
        ordered=True,
        stream=stream,
        group=consumer_group_name(consumer.name, computer),
        consumer_name=consumer_reader_name(consumer.name, computer),
    )


class RetainedHandover:
    """A retained consumer that no longer reads the cluster Redis: it finishes its old cluster group, then reads locally.

    The local reader's position is taken before producers run, so entries that arrive while the old group drains wait
    for it; the drain hands over every entry the consumer was owed there, in order, and retires the group.
    """

    def __init__(self, drain: EventProcessor[StreamEvent], local: EventProcessor[StreamEvent]) -> None:
        self._drain = drain
        self._local = local

    async def prepare_group_position(self) -> None:
        """Take the local position; the old group keeps its own."""
        await self._local.prepare_group_position()

    async def start(self, shutdown_event: asyncio.Event) -> None:
        """Drain and retire the old cluster group when it exists, then read locally until shutdown."""
        await self._drain.drain_and_retire(shutdown_event)
        if not shutdown_event.is_set():
            await self._local.start(shutdown_event)


type _Reader = EventProcessor[StreamEvent] | SharedLiveFeed | RetainedHandover


@dataclass(frozen=True)
class _Runner:
    """One reader, with the Redis clients it reads: it runs only while every one of them answers."""

    name: str
    processor: _Reader
    clients: tuple[Any, ...]


def _answers_all(runner: _Runner, answering: Collection[object] | None) -> bool:
    return answering is None or all(any(client is known for known in answering) for client in runner.clients)


class ConsumerRuntime:
    """Compose independent retained and live readers on one computer, each on the Redis of a scope it reads.

    A reader waits for the Redis it reads: its position is taken and its run starts only while that Redis answers,
    and a retained reader whose Redis stops answering waits for it and resumes from its group.
    """

    def __init__(
        self,
        consumers: Sequence[Consumer],
        *,
        redis_clients: ScopedClients[Any],
        reachability: RedisReachability,
        db: EventDB,
        computer: str,
        stream: str = STREAM_NAME,
        codec: EntryCodec[StreamEvent] = PLATFORM_ENTRY_CODEC,
    ) -> None:
        names = [consumer.name for consumer in consumers]
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise ValueError(_DUPLICATE_NAMES_ERROR.format(names=_NAME_SEPARATOR.join(repeated)))
        self._reachability = reachability
        self._runners: list[_Runner] = []
        self._prepared: set[str] = set()
        self._supervised: set[str] = set()
        live_views: dict[EventScope, list[LiveEventReader]] = {}
        live_clients: dict[EventScope, Any] = {}
        for consumer in consumers:
            pipeline = _ConsumerPipeline(consumer, db, computer)
            read_clients: list[object] = []
            scopes = scopes_of_interest(consumer.interest.types)
            # A consumer that reads only local events once read the cluster Redis, which may still hold entries for it.
            hands_over = EventScope.CLUSTER not in scopes and redis_clients.local is not redis_clients.cluster
            for scope in sorted(scopes):
                client = redis_clients.for_scope(scope)
                # Scopes that share one Redis are read once.
                if any(client is read for read in read_clients):
                    continue
                read_clients.append(client)
                if consumer.delivery is ConsumerDelivery.LIVE:
                    feed_scope = next(
                        (known for known, known_client in live_clients.items() if known_client is client), scope
                    )
                    live_clients[feed_scope] = client
                    live_views.setdefault(feed_scope, []).append(
                        _live_view(consumer, pipeline, client, computer, stream, codec)
                    )
                    continue
                local_reader = _retained_reader(consumer, pipeline, client, computer, stream, codec)
                reader: EventProcessor[StreamEvent] | RetainedHandover = local_reader
                read: tuple[Any, ...] = (client,)
                if hands_over:
                    drain = _retained_reader(consumer, pipeline, redis_clients.cluster, computer, stream, codec)
                    reader = RetainedHandover(drain, local_reader)
                    read = (client, redis_clients.cluster)
                name = _SCOPED_NAME_TEMPLATE.format(name=consumer.name, scope=scope.value)
                self._runners.append(_Runner(name, reader, read))
        for scope, views in live_views.items():
            feed = SharedLiveFeed(cast(LiveStreamClient, live_clients[scope]), stream=stream, readers=views)
            name = _SCOPED_NAME_TEMPLATE.format(name=_LIVE_FEED_NAME, scope=scope.value)
            self._runners.append(_Runner(name, feed, (live_clients[scope],)))

    def unattached(self) -> bool:
        """Whether some reader has no position yet or does not run yet."""
        return len(self._supervised) < len(self._runners)

    async def prepare_group_positions(self, answering: Collection[object] | None = None) -> None:
        """Prepare retained positions and live boundaries before any handler executes.

        Acts only on readers not yet prepared whose every Redis is among the answering clients (all, by default);
        a reader whose Redis does not answer stays unprepared for a later call.
        """
        await asyncio.gather(
            *(
                self._prepare_one(runner)
                for runner in self._runners
                if runner.name not in self._prepared and _answers_all(runner, answering)
            )
        )

    async def _prepare_one(self, runner: _Runner) -> None:
        if await self._reachability.attempt(runner.clients, runner.processor.prepare_group_position):
            self._prepared.add(runner.name)

    def supervise(
        self,
        registry: TaskRegistry,
        shutdown_event: asyncio.Event,
        answering: Collection[object] | None = None,
    ) -> tuple[SupervisedTask, ...]:
        """Run each prepared consumer until shutdown as its own supervised task: one that ends is replaced alone.

        Acts only on prepared readers not yet running whose every Redis is among the answering clients (all, by
        default), so a later call starts exactly the remainder.
        """
        started = [
            runner
            for runner in self._runners
            if runner.name in self._prepared and runner.name not in self._supervised and _answers_all(runner, answering)
        ]
        self._supervised.update(runner.name for runner in started)
        return tuple(
            registry.supervise(
                _CONSUMER_TASK_TEMPLATE.format(name=runner.name),
                partial(self._run_one, runner, shutdown_event),
                restart=True,
            )
            for runner in started
        )

    async def _run_one(self, runner: _Runner, shutdown_event: asyncio.Event) -> None:
        logger.info(_CONSUMER_STARTED_EVENT, consumer=runner.name)
        if isinstance(runner.processor, SharedLiveFeed):
            # A live feed contains its own read errors and recovers its source.
            await runner.processor.start(shutdown_event)
            return
        await self._run_retained(runner.processor, runner.clients, shutdown_event)

    async def _run_retained(
        self,
        processor: EventProcessor[StreamEvent] | RetainedHandover,
        clients: tuple[Any, ...],
        shutdown_event: asyncio.Event,
    ) -> None:
        """Run a retained reader until shutdown, waiting out its Redis whenever it stops answering.

        Re-entering `start` resumes from the consumer group: pending entries first and in order, then new ones.
        Every failure that is not the Redis not answering ends the run for its supervisor.
        """
        while await self._reachability.until_answering(*clients):
            try:
                await processor.start(shutdown_event)
            except Exception as error:
                if not is_redis_unreachable(error):
                    raise
                self._reachability.mark_lost(clients, error)
                continue
            return
