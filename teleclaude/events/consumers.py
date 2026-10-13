"""Event consumers: independent reactions to platform events, each with its own progress through the stream.

A consumer is a declared name, an interest and a handler. The runtime gives every consumer its own
consumer group and a stable reader name on the platform stream, so its progress, retries and dead
letters are its own and one consumer's failure or lag never holds back or hides another. Selection
reads the event's attributes only; a handler is handed the received event and nothing else. The
platform hands a consumer each event once: a record of handled event ids, kept per consumer in the
computer's events database, makes a repeat skip, while handling that was interrupted before its
record was written is handed again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any

from instrukt_ai_logging import get_logger

from teleclaude.events.db import EventDB
from teleclaude.events.envelope import EventHomeKind, EventHomeRef, ReceivedEvent
from teleclaude.events.processor import EventProcessor
from teleclaude.events.references import ReferenceKind
from teleclaude.events.type_pattern import TypePattern
from teleclaude.events.wire import PLATFORM_ENTRY_CODEC, StreamEvent

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
_CONSUMER_TASK_TEMPLATE = "event-consumer-{name}"


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

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError(_NO_NAME_ERROR)


def _received(event: StreamEvent) -> ReceivedEvent:
    """The event as every reader sees it, without the notification path's legacy facts."""
    return ReceivedEvent.model_validate({name: getattr(event, name) for name in ReceivedEvent.model_fields})


class _ConsumerPipeline:
    """The stream-entry pipeline of one consumer: select, skip a handled repeat, hand over, then record."""

    def __init__(self, consumer: Consumer, db: EventDB, computer: str) -> None:
        self._consumer = consumer
        self._db = db
        self._computer = computer

    async def execute(self, event: StreamEvent, /) -> None:
        """Hand the event to the consumer once; a handler failure propagates to the processor's retry."""
        consumer = self._consumer
        if not consumer.interest.selects(event, self._computer):
            return
        if await self._db.has_handled_event(consumer.name, event.id):
            return
        await consumer.handler(_received(event))
        await self._db.record_handled_event(consumer.name, event.id, datetime.now(UTC))


class ConsumerRuntime:
    """Runs a set of consumers on this computer, each as its own ordered reader of the platform stream."""

    def __init__(
        self,
        consumers: Sequence[Consumer],
        *,
        redis_client: Any,
        db: EventDB,
        computer: str,
    ) -> None:
        names = [consumer.name for consumer in consumers]
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise ValueError(_DUPLICATE_NAMES_ERROR.format(names=_NAME_SEPARATOR.join(repeated)))
        self._processors = [
            (
                consumer.name,
                EventProcessor(
                    redis_client,
                    _ConsumerPipeline(consumer, db, computer),
                    codec=PLATFORM_ENTRY_CODEC,
                    declared_name=consumer.name,
                    ordered=True,
                    group=_GROUP_TEMPLATE.format(name=consumer.name, computer=computer),
                    consumer_name=_READER_TEMPLATE.format(name=consumer.name, computer=computer),
                ),
            )
            for consumer in consumers
        ]

    def supervise(self, registry: TaskRegistry, shutdown_event: asyncio.Event) -> tuple[SupervisedTask, ...]:
        """Run every consumer until shutdown as its own supervised task: one that ends is replaced alone."""
        return tuple(
            registry.supervise(
                _CONSUMER_TASK_TEMPLATE.format(name=name),
                partial(self._run_one, name, processor, shutdown_event),
                restart=True,
            )
            for name, processor in self._processors
        )

    async def _run_one(self, name: str, processor: EventProcessor[StreamEvent], shutdown_event: asyncio.Event) -> None:
        logger.info(_CONSUMER_STARTED_EVENT, consumer=name)
        await processor.start(shutdown_event)
