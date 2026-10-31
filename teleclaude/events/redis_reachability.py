"""Reachability of each event Redis: one record per distinct client, one wait loop per Redis.

A reader waits on the record of the Redis it reads and resumes when that Redis answers again; an outage is never
a reader's end. Whoever meets a reachability failure marks that Redis lost, which logs the loss once and starts the
single paced ping loop that wakes every waiter and logs the return once. Logs, snapshots and status name scopes and
error classes only, because an error message can embed the Redis URL and credentials.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from instrukt_ai_logging import get_logger
from redis.exceptions import AuthenticationError, AuthorizationError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from teleclaude.events.scope import EventScope, ScopedClients

logger = get_logger(__name__)

#: How long one ping may take before the Redis counts as not answering.
PING_DEADLINE_S: Final = 3.0
#: The pause between a lost Redis's pings.
PING_INTERVAL_S: Final = 5.0
#: How long one startup or attach operation on a Redis may take before that Redis counts as not answering.
OPERATION_DEADLINE_S: Final = 10.0

_LOST_EVENT: Final = "event_redis_unreachable"
_ANSWERING_EVENT: Final = "event_redis_answering"
_STATE_KEY: Final = "daemon"
_STATE: dict[str, RedisReachability] = {}


def is_redis_unreachable(error: BaseException) -> bool:
    """Whether a failure is the Redis not answering: a refused or reset connection, or a timeout.

    A rejected credential is the server answering, so it is not reachability, even though the client library
    raises it as a connection error. A group of failures is reachability only when every failure in it is.
    """
    if isinstance(error, BaseExceptionGroup):
        return bool(error.exceptions) and all(is_redis_unreachable(leaf) for leaf in error.exceptions)
    if isinstance(error, AuthenticationError | AuthorizationError):
        return False
    return isinstance(error, RedisConnectionError | RedisTimeoutError)


def _error_class(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup) and error.exceptions:
        return _error_class(error.exceptions[0])
    return type(error).__name__


@dataclass
class _Record:
    client: Any
    scopes: tuple[EventScope, ...]
    answering: asyncio.Event = field(default_factory=asyncio.Event)
    ping_loop: asyncio.Task[None] | None = None

    def __post_init__(self) -> None:
        self.answering.set()


class RedisReachability:
    """The reachability of every distinct Redis client of an event platform's scopes."""

    def __init__(self, clients: ScopedClients[Any], shutdown_event: asyncio.Event) -> None:
        self._shutdown = shutdown_event
        self._records = tuple(
            _Record(client, tuple(scope for scope in EventScope if clients.for_scope(scope) is client))
            for client in clients.distinct()
        )

    def _record(self, client: object) -> _Record:
        return next(record for record in self._records if record.client is client)

    def answering_clients(self) -> tuple[Any, ...]:
        """The clients whose Redis answers now."""
        return tuple(record.client for record in self._records if record.answering.is_set())

    def unanswering_clients(self) -> tuple[Any, ...]:
        """The clients whose Redis does not answer now."""
        return tuple(record.client for record in self._records if not record.answering.is_set())

    def unanswering_scopes(self) -> tuple[EventScope, ...]:
        """The scopes whose Redis does not answer now, in scope order."""
        lost = {scope for record in self._records if not record.answering.is_set() for scope in record.scopes}
        return tuple(scope for scope in EventScope if scope in lost)

    async def probe(self) -> None:
        """Ping each Redis once, bounded by the ping deadline; a Redis that does not answer is marked lost.

        A failure that is not reachability, such as a rejected credential, propagates.
        """
        await asyncio.gather(*(self._probe_one(record) for record in self._records))

    async def _probe_one(self, record: _Record) -> None:
        try:
            await asyncio.wait_for(record.client.ping(), PING_DEADLINE_S)
        except TimeoutError as error:
            self.mark_lost((record.client,), error)
        except Exception as error:
            if not is_redis_unreachable(error):
                raise
            self.mark_lost((record.client,), error)

    async def attempt(self, clients: Sequence[object], operation: Callable[[], Awaitable[object]]) -> bool:
        """Run an operation on these clients' Redis; one that fails to reach it, or outlasts the operation deadline,
        marks them lost and returns False.

        Every other failure propagates.
        """
        try:
            await asyncio.wait_for(operation(), OPERATION_DEADLINE_S)
        except TimeoutError as error:
            self.mark_lost(clients, error)
            return False
        except Exception as error:
            if not is_redis_unreachable(error):
                raise
            self.mark_lost(clients, error)
            return False
        return True

    def mark_lost(self, clients: Iterable[object], error: BaseException) -> None:
        """Record that these clients' Redis does not answer: log each loss once and wait for its return."""
        for client in clients:
            record = self._record(client)
            if not record.answering.is_set():
                continue
            record.answering.clear()
            logger.warning(
                _LOST_EVENT,
                scopes=[scope.value for scope in record.scopes],
                error_class=_error_class(error),
            )
            record.ping_loop = asyncio.create_task(self._ping_until_answering(record))

    async def _ping_until_answering(self, record: _Record) -> None:
        while not self._shutdown.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._shutdown.wait(), PING_INTERVAL_S)
            if self._shutdown.is_set():
                return
            try:
                await asyncio.wait_for(record.client.ping(), PING_DEADLINE_S)
            except TimeoutError:
                continue
            except Exception as error:
                # A rejected credential is the server answering; the readers resume and surface it themselves.
                if is_redis_unreachable(error):
                    continue
            record.answering.set()
            logger.info(_ANSWERING_EVENT, scopes=[scope.value for scope in record.scopes])
            return

    async def until_answering(self, *clients: object) -> bool:
        """Wait until every one of these clients' Redis answers; False when shutdown comes first."""
        for client in clients:
            if not await self._wait(self._record(client).answering):
                return False
        return True

    async def until_any_answers(self, clients: Sequence[object]) -> bool:
        """Wait until at least one of these clients' Redis answers; False when shutdown comes first."""
        waits = [asyncio.create_task(self._wait(self._record(client).answering)) for client in clients]
        try:
            done, _ = await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            return any(task.result() for task in done)
        finally:
            for wait in waits:
                wait.cancel()
            await asyncio.gather(*waits, return_exceptions=True)

    async def _wait(self, answering: asyncio.Event) -> bool:
        if answering.is_set():
            return True
        shutdown = asyncio.create_task(self._shutdown.wait())
        answered = asyncio.create_task(answering.wait())
        try:
            await asyncio.wait((shutdown, answered), return_when=asyncio.FIRST_COMPLETED)
            return answering.is_set()
        finally:
            shutdown.cancel()
            answered.cancel()
            await asyncio.gather(shutdown, answered, return_exceptions=True)

    async def aclose(self) -> None:
        """Stop every ping loop and withdraw this owner's published snapshot."""
        loops = [record.ping_loop for record in self._records if record.ping_loop is not None]
        for loop in loops:
            loop.cancel()
        await asyncio.gather(*loops, return_exceptions=True)
        if _STATE.get(_STATE_KEY) is self:
            del _STATE[_STATE_KEY]


def configure_reachability(owner: RedisReachability) -> None:
    """Publish the daemon's reachability owner for the readiness surface."""
    _STATE[_STATE_KEY] = owner


def unanswering_event_scopes() -> tuple[EventScope, ...]:
    """The event scopes whose Redis does not answer now; none when no owner is published."""
    owner = _STATE.get(_STATE_KEY)
    return owner.unanswering_scopes() if owner is not None else ()
