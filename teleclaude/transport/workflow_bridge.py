"""Redis subscriber that bridges v2 `workflow.*` events into the v1 daemon.

The v2 Rust services publish workflow domain events to Redis pub/sub channels
matching ``workflow.*`` (see ``docs/project/design/architecture-v2/event-bus-transports.md``).
This module subscribes to those channels, decodes the envelope, and routes each
event through a caller-provided dispatch sink — typically wiring cache
invalidation and a WebSocket refresh push.

Scope notes:

* Bridge is intentionally agnostic of the v1 cache/WS internals. The daemon
  composes the dispatch sink that mutates ``DaemonCache``.
* Idempotency is enforced in-memory only. After a daemon restart, recently-seen
  envelope keys are forgotten; this is acceptable for the MVP bridge because
  the downstream effect (cache invalidation) is idempotent.
* Reconnects use exponential backoff capped at 30 s.
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
WORKFLOW_PATTERN = "workflow.*"

# Channel category prefixes used for dispatch routing.
TODO_PREFIX = "workflow.todo."
ROADMAP_PREFIX = "workflow.roadmap."
ARTIFACT_PREFIX = "workflow.artifact."

WorkflowCategory = Literal["todo", "roadmap", "artifact"]


@dataclass(frozen=True)
class WorkflowEnvelope:
    """Decoded envelope published by the v2 event-bus crate."""

    channel: str
    idempotency_key: str
    emitted_at: str
    principal: dict[str, object] | None  # guard: loose-dict - v2 Principal shape varies by kind
    payload: dict[str, object]  # guard: loose-dict - event-specific JSON payload, not parsed here

    @property
    def category(self) -> WorkflowCategory | None:
        """Return the routing category, or ``None`` for unknown channels."""
        if self.channel.startswith(TODO_PREFIX):
            return "todo"
        if self.channel.startswith(ROADMAP_PREFIX):
            return "roadmap"
        if self.channel.startswith(ARTIFACT_PREFIX):
            return "artifact"
        return None

    @property
    def principal_kind(self) -> str | None:
        """Return the principal kind/type when present, for structured logging."""
        if self.principal is None:
            return None
        kind = self.principal.get("kind") or self.principal.get("type")
        return kind if isinstance(kind, str) else None


WorkflowDispatcher = Callable[[WorkflowEnvelope], None]


class MalformedEnvelopeError(ValueError):
    """Raised when a Redis pub/sub payload cannot be decoded into a WorkflowEnvelope."""


def decode_envelope(raw: bytes | str) -> WorkflowEnvelope:
    """Parse a Redis pub/sub payload into a :class:`WorkflowEnvelope`.

    Args:
        raw: Raw envelope bytes or string as published by the v2 event bus.

    Returns:
        Decoded envelope.

    Raises:
        MalformedEnvelopeError: When the payload is not valid JSON or is missing
            required fields.
    """
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalformedEnvelopeError("envelope is not valid UTF-8") from exc
    else:
        text = raw

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedEnvelopeError("envelope is not valid JSON") from exc

    if not isinstance(data, dict):
        raise MalformedEnvelopeError("envelope is not a JSON object")

    channel = data.get("channel")
    idempotency_key = data.get("idempotency_key")
    emitted_at = data.get("emitted_at")
    payload = data.get("payload")
    principal = data.get("principal")

    if not isinstance(channel, str) or not channel:
        raise MalformedEnvelopeError("envelope.channel is missing or empty")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise MalformedEnvelopeError("envelope.idempotency_key is missing or empty")
    if not isinstance(emitted_at, str) or not emitted_at:
        raise MalformedEnvelopeError("envelope.emitted_at is missing or empty")
    if not isinstance(payload, dict):
        raise MalformedEnvelopeError("envelope.payload is missing or not an object")
    if principal is not None and not isinstance(principal, dict):
        raise MalformedEnvelopeError("envelope.principal must be an object when present")

    return WorkflowEnvelope(
        channel=channel,
        idempotency_key=idempotency_key,
        emitted_at=emitted_at,
        principal=principal,
        payload=payload,
    )


class _IdempotencyCache:
    """Bounded LRU set of idempotency keys.

    Tracks recently observed envelope keys so that consumer-group redelivery or
    duplicate publishes do not double-dispatch.
    """

    def __init__(self, max_size: int) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._max_size = max_size
        # OrderedDict acts as an insertion-ordered LRU; value is unused.
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


class WorkflowBridge:
    """Subscribe to ``workflow.*`` and route each envelope through a dispatch sink.

    The bridge is loop-friendly: ``run()`` is meant to be wrapped in
    ``asyncio.create_task``. It survives Redis disconnects via exponential
    backoff and survives malformed envelopes by logging at WARN and continuing.
    """

    def __init__(
        self,
        *,
        redis_factory: Callable[[], Redis],
        dispatch: WorkflowDispatcher,
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

    def process_envelope(self, envelope: WorkflowEnvelope) -> bool:
        """Dispatch a decoded envelope, applying idempotency dedup.

        Returns:
            True if the envelope was dispatched, False if it was deduped or
            its channel did not match a known category.
        """
        if envelope.category is None:
            logger.warning(
                "Dropping workflow envelope with unrecognized channel",
                channel=envelope.channel,
                idempotency_key=envelope.idempotency_key,
            )
            return False

        if not self._idempotency.seen(envelope.idempotency_key):
            logger.debug(
                "Skipping duplicate workflow envelope",
                channel=envelope.channel,
                idempotency_key=envelope.idempotency_key,
            )
            return False

        try:
            self._dispatch(envelope)
        except Exception:
            logger.exception(
                "Workflow dispatcher raised; continuing subscriber loop",
                channel=envelope.channel,
                idempotency_key=envelope.idempotency_key,
                principal_kind=envelope.principal_kind,
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
                # Clean stop from the inner loop — bail out without sleeping.
                return
            except (RedisError, ConnectionError, OSError, TimeoutError) as exc:
                logger.error(
                    "Workflow Redis subscriber connection error; retrying with backoff",
                    error=str(exc),
                    backoff_s=backoff,
                )
                await self._sleep(backoff)
                backoff = min(backoff * 2.0, self._max_backoff_s)
            except Exception:
                # Last-resort guard: keep the daemon alive even on unexpected faults.
                logger.exception(
                    "Workflow Redis subscriber crashed unexpectedly; retrying with backoff",
                    backoff_s=backoff,
                )
                await self._sleep(backoff)
                backoff = min(backoff * 2.0, self._max_backoff_s)

    async def _run_once(self) -> None:
        """Open one Redis pub/sub session and consume until error or stop."""
        client = self._redis_factory()
        pubsub = cast(RedisPubSub, client.pubsub())
        await pubsub.psubscribe(WORKFLOW_PATTERN)
        logger.info("Workflow Redis subscriber attached", pattern=WORKFLOW_PATTERN)
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
                await pubsub.punsubscribe(WORKFLOW_PATTERN)
                await pubsub.aclose()
            except Exception:
                logger.debug("Error closing workflow pubsub", exc_info=True)

    def _handle_raw_message(self, raw: object) -> None:
        """Decode and dispatch a single pub/sub payload, tolerating decode errors."""
        if not isinstance(raw, (bytes, str)):
            logger.warning("Workflow envelope payload has unexpected type", payload_type=type(raw).__name__)
            return
        try:
            envelope = decode_envelope(raw)
        except MalformedEnvelopeError as exc:
            logger.warning("Malformed workflow envelope; dropping", error=str(exc))
            return
        self.process_envelope(envelope)
