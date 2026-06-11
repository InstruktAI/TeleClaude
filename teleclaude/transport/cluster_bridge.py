"""Redis subscriber that bridges cross-computer ``cluster.*`` events into the daemon.

``cluster.*`` is the v1 cross-computer event namespace: every daemon publishes
state mutations (session created, project registered, todo updated, computer
identity updated) to ``cluster.{aggregate}.{kind}`` channels, and every daemon
subscribes to the whole pattern. Local mutations round-trip through Redis
back to the publisher's own ``ClusterBridge``, so a single dispatch path
writes to the local cache regardless of which computer originated the change.

The envelope shape mirrors :mod:`teleclaude.transport.workflow_bridge` for
parity with the v2 event bus, plus an ``origin`` field that identifies the
publishing computer. The dispatch sink uses ``origin`` to skip a re-publish
when handling its own events.

Scope notes:

* Bridge stays agnostic of cache internals; the daemon composes the dispatch
  callback. Per :doc:`project/policy/adapter-boundaries`.
* Idempotency LRU is in-memory only; the bootstrap snapshot covers events
  missed while a subscriber was offline.
* Reconnects use exponential backoff capped at 30 s, matching the v2 bridges.
"""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.transport._redis_pubsub import RedisPubSub

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)


# Channel pattern subscribed via Redis pub/sub ``PSUBSCRIBE``.
CLUSTER_PATTERN = "cluster.*"
CLUSTER_ENVELOPE_SCHEMA_VERSION = 1

# Channel category prefixes used for dispatch routing.
SESSION_PREFIX = "cluster.session."
PROJECT_PREFIX = "cluster.project."
TODO_PREFIX = "cluster.todo."
COMPUTER_PREFIX = "cluster.computer."

ClusterCategory = Literal["session", "project", "todo", "computer"]


@dataclass(frozen=True)
class ClusterEnvelope:
    """Decoded envelope published on a ``cluster.*`` channel.

    The envelope is the cross-computer event contract. ``origin`` names the
    publishing computer so receivers can distinguish self-published events
    (which still need cache updates but must not re-publish). The current
    envelope shape is schema version 1; missing versions decode as legacy v1.
    """

    schema_version: int
    channel: str
    idempotency_key: str
    emitted_at: str
    origin: str
    payload: dict[str, object]  # guard: loose-dict - event-specific payload, not parsed here

    @property
    def category(self) -> ClusterCategory | None:
        """Return the routing category, or ``None`` for unknown channels."""
        if self.channel.startswith(SESSION_PREFIX):
            return "session"
        if self.channel.startswith(PROJECT_PREFIX):
            return "project"
        if self.channel.startswith(TODO_PREFIX):
            return "todo"
        if self.channel.startswith(COMPUTER_PREFIX):
            return "computer"
        return None


ClusterDispatcher = Callable[[ClusterEnvelope], None]


class MalformedClusterEnvelopeError(ValueError):
    """Raised when a Redis pub/sub payload cannot be decoded into a ClusterEnvelope."""


def decode_envelope(raw: bytes | str) -> ClusterEnvelope:
    """Parse a Redis pub/sub payload into a :class:`ClusterEnvelope`.

    Raises:
        MalformedClusterEnvelopeError: When the payload is not valid JSON or
            is missing required fields.
    """
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalformedClusterEnvelopeError("envelope is not valid UTF-8") from exc
    else:
        text = raw

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedClusterEnvelopeError("envelope is not valid JSON") from exc

    if not isinstance(data, dict):
        raise MalformedClusterEnvelopeError("envelope is not a JSON object")

    channel = data.get("channel")
    idempotency_key = data.get("idempotency_key")
    emitted_at = data.get("emitted_at")
    origin = data.get("origin")
    payload = data.get("payload")
    schema_version = data.get("schema_version", CLUSTER_ENVELOPE_SCHEMA_VERSION)

    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
        raise MalformedClusterEnvelopeError("envelope.schema_version is missing or invalid")
    if not isinstance(channel, str) or not channel:
        raise MalformedClusterEnvelopeError("envelope.channel is missing or empty")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise MalformedClusterEnvelopeError("envelope.idempotency_key is missing or empty")
    if not isinstance(emitted_at, str) or not emitted_at:
        raise MalformedClusterEnvelopeError("envelope.emitted_at is missing or empty")
    if not isinstance(origin, str) or not origin:
        raise MalformedClusterEnvelopeError("envelope.origin is missing or empty")
    if not isinstance(payload, dict):
        raise MalformedClusterEnvelopeError("envelope.payload is missing or not an object")

    return ClusterEnvelope(
        schema_version=schema_version,
        channel=channel,
        idempotency_key=idempotency_key,
        emitted_at=emitted_at,
        origin=origin,
        payload=payload,
    )


class _IdempotencyCache:
    """Bounded LRU set of idempotency keys."""

    def __init__(self, max_size: int) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._max_size = max_size
        self._seen: OrderedDict[str, None] = OrderedDict()

    def seen(self, key: str) -> bool:
        """Return True if the key is new (and record it); False if duplicate."""
        if key in self._seen:
            self._seen.move_to_end(key)
            return False
        self._seen[key] = None
        if len(self._seen) > self._max_size:
            self._seen.popitem(last=False)
        return True


class ClusterBridge:
    """Subscribe to ``cluster.*`` and route each envelope through a dispatch sink.

    Loop-friendly: ``run()`` is meant to be wrapped in ``asyncio.create_task``.
    Survives Redis disconnects via exponential backoff and survives malformed
    envelopes by logging at WARN and continuing.
    """

    def __init__(
        self,
        *,
        redis_factory: Callable[[], Redis],
        dispatch: ClusterDispatcher,
        cache_size: int = 4096,
        initial_backoff_s: float = 1.0,
        max_backoff_s: float = 30.0,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._redis_factory = redis_factory
        self._dispatch = dispatch
        self._idempotency = _IdempotencyCache(cache_size)
        self._initial_backoff_s = initial_backoff_s
        self._max_backoff_s = max_backoff_s
        self._sleep = sleep if sleep is not None else asyncio.sleep
        self._running = False
        self._stop_event = asyncio.Event()

    def process_envelope(self, envelope: ClusterEnvelope) -> bool:
        """Dispatch a decoded envelope, applying idempotency dedup.

        Returns:
            True if the envelope was dispatched, False if it was deduped or
            its channel did not match a known category.
        """
        if envelope.category is None:
            logger.warning(
                "Dropping cluster envelope with unrecognized channel",
                channel=envelope.channel,
                idempotency_key=envelope.idempotency_key,
            )
            return False

        if not self._idempotency.seen(envelope.idempotency_key):
            logger.debug(
                "Skipping duplicate cluster envelope",
                channel=envelope.channel,
                idempotency_key=envelope.idempotency_key,
            )
            return False

        try:
            self._dispatch(envelope)
        except Exception:
            logger.exception(
                "Cluster dispatcher raised; continuing subscriber loop",
                channel=envelope.channel,
                idempotency_key=envelope.idempotency_key,
                origin=envelope.origin,
            )
            return False
        return True

    async def stop(self) -> None:
        """Signal the run loop to terminate at the next iteration."""
        self._running = False
        self._stop_event.set()

    async def run(self) -> None:
        """Subscriber loop. Returns when ``stop()`` is called."""
        self._running = True
        self._stop_event.clear()
        backoff = self._initial_backoff_s
        while self._running:
            try:
                await self._run_once()
                return
            except (RedisError, ConnectionError, OSError, TimeoutError) as exc:
                logger.error(
                    "Cluster Redis subscriber connection error; retrying with backoff",
                    error=str(exc),
                    backoff_s=backoff,
                )
                await self._sleep(backoff)
                backoff = min(backoff * 2.0, self._max_backoff_s)
            except Exception:
                logger.exception(
                    "Cluster Redis subscriber crashed unexpectedly; retrying with backoff",
                    backoff_s=backoff,
                )
                await self._sleep(backoff)
                backoff = min(backoff * 2.0, self._max_backoff_s)

    async def _run_once(self) -> None:
        """Open one Redis pub/sub session and consume until error or stop."""
        client = self._redis_factory()
        pubsub = cast(RedisPubSub, client.pubsub())
        await pubsub.psubscribe(CLUSTER_PATTERN)
        logger.info("Cluster Redis subscriber attached", pattern=CLUSTER_PATTERN)
        try:
            while self._running:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    continue
                if message.get("type") not in ("pmessage", "message"):
                    continue
                self._handle_raw_message(message.get("data"))
        finally:
            try:
                await pubsub.punsubscribe(CLUSTER_PATTERN)
                await pubsub.aclose()
            except Exception:
                logger.debug("Error closing cluster pubsub", exc_info=True)

    def _handle_raw_message(self, raw: object) -> None:
        """Decode and dispatch a single pub/sub payload, tolerating decode errors."""
        if not isinstance(raw, bytes | str):
            logger.warning(
                "Cluster envelope payload has unexpected type",
                payload_type=type(raw).__name__,
            )
            return
        try:
            envelope = decode_envelope(raw)
        except MalformedClusterEnvelopeError as exc:
            logger.warning("Malformed cluster envelope; dropping", error=str(exc))
            return
        self.process_envelope(envelope)
