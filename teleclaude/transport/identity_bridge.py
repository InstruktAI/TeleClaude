"""Redis subscriber that bridges v2 ``identity.*`` events into the v1 daemon.

Mirrors :mod:`teleclaude.transport.workflow_bridge` so the v1 daemon can
react to identity-service mutations published by the v2 Rust ``identity``
crate — principal creation, token issuance, token revocation.

The MVP dispatch is intentionally minimal: v1 has no identity cache that
benefits from invalidation today, so the bridge logs each envelope at
INFO and hands the decoded :class:`IdentityEnvelope` to the caller-
supplied dispatcher. Future work can wire cache invalidation or any
other reactive behavior into the dispatch callback without touching the
subscriber loop.

Scope notes:

* Bridge stays agnostic of v1 cache internals; the daemon composes the
  dispatch callback.
* Idempotency is enforced in-memory only. After a daemon restart,
  recently-seen envelope keys are forgotten; this is acceptable because
  the downstream effect is currently log-only.
* Reconnects use exponential backoff capped at 30 s.
"""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)


# Channel pattern subscribed via Redis pub/sub ``PSUBSCRIBE``.
IDENTITY_PATTERN = "identity.*"

# Channel category prefixes used for dispatch routing.
PRINCIPAL_PREFIX = "identity.principal."
TOKEN_PREFIX = "identity.token."

IdentityCategory = Literal["principal", "token"]


@dataclass(frozen=True)
class IdentityEnvelope:
    """Decoded envelope published by the v2 ``identity`` service."""

    channel: str
    idempotency_key: str
    emitted_at: str
    principal: dict[str, object] | None  # guard: loose-dict - v2 Principal shape varies by kind
    payload: dict[str, object]  # guard: loose-dict - event-specific payload, not parsed here

    @property
    def category(self) -> IdentityCategory | None:
        """Return the routing category, or ``None`` for unknown channels."""
        if self.channel.startswith(PRINCIPAL_PREFIX):
            return "principal"
        if self.channel.startswith(TOKEN_PREFIX):
            return "token"
        return None

    @property
    def principal_kind(self) -> str | None:
        """Return the principal kind/type when present, for structured logging."""
        if self.principal is None:
            return None
        kind = self.principal.get("kind") or self.principal.get("type")
        return kind if isinstance(kind, str) else None


IdentityDispatcher = Callable[[IdentityEnvelope], None]


class MalformedIdentityEnvelopeError(ValueError):
    """Raised when a Redis pub/sub payload cannot be decoded into an IdentityEnvelope."""


def decode_envelope(raw: bytes | str) -> IdentityEnvelope:
    """Parse a Redis pub/sub payload into an :class:`IdentityEnvelope`.

    Args:
        raw: Raw envelope bytes or string as published by the v2 event bus.

    Returns:
        Decoded envelope.

    Raises:
        MalformedIdentityEnvelopeError: When the payload is not valid JSON
            or is missing required fields.
    """
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalformedIdentityEnvelopeError("envelope is not valid UTF-8") from exc
    else:
        text = raw

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedIdentityEnvelopeError("envelope is not valid JSON") from exc

    if not isinstance(data, dict):
        raise MalformedIdentityEnvelopeError("envelope is not a JSON object")

    channel = data.get("channel")
    idempotency_key = data.get("idempotency_key")
    emitted_at = data.get("emitted_at")
    payload = data.get("payload")
    principal = data.get("principal")

    if not isinstance(channel, str) or not channel:
        raise MalformedIdentityEnvelopeError("envelope.channel is missing or empty")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise MalformedIdentityEnvelopeError("envelope.idempotency_key is missing or empty")
    if not isinstance(emitted_at, str) or not emitted_at:
        raise MalformedIdentityEnvelopeError("envelope.emitted_at is missing or empty")
    if not isinstance(payload, dict):
        raise MalformedIdentityEnvelopeError("envelope.payload is missing or not an object")
    if principal is not None and not isinstance(principal, dict):
        raise MalformedIdentityEnvelopeError("envelope.principal must be an object when present")

    return IdentityEnvelope(
        channel=channel,
        idempotency_key=idempotency_key,
        emitted_at=emitted_at,
        principal=principal,
        payload=payload,
    )


class _IdempotencyCache:
    """Bounded LRU set of idempotency keys.

    Tracks recently observed envelope keys so that consumer-group redelivery
    or duplicate publishes do not double-dispatch.
    """

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


class IdentityBridge:
    """Subscribe to ``identity.*`` and route each envelope through a dispatch sink.

    The bridge is loop-friendly: ``run()`` is meant to be wrapped in
    ``asyncio.create_task``. It survives Redis disconnects via exponential
    backoff and survives malformed envelopes by logging at WARN and
    continuing.
    """

    def __init__(
        self,
        *,
        redis_factory: Callable[[], Redis],
        dispatch: IdentityDispatcher,
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

    def process_envelope(self, envelope: IdentityEnvelope) -> bool:
        """Dispatch a decoded envelope, applying idempotency dedup.

        Returns:
            True if the envelope was dispatched, False if it was deduped or
            its channel did not match a known category.
        """
        if envelope.category is None:
            logger.warning(
                "Dropping identity envelope with unrecognized channel",
                channel=envelope.channel,
                idempotency_key=envelope.idempotency_key,
            )
            return False

        if not self._idempotency.seen(envelope.idempotency_key):
            logger.debug(
                "Skipping duplicate identity envelope",
                channel=envelope.channel,
                idempotency_key=envelope.idempotency_key,
            )
            return False

        try:
            self._dispatch(envelope)
        except Exception:
            logger.exception(
                "Identity dispatcher raised; continuing subscriber loop",
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
                return
            except (RedisError, ConnectionError, OSError, TimeoutError) as exc:
                logger.error(
                    "Identity Redis subscriber connection error; retrying with backoff",
                    error=str(exc),
                    backoff_s=backoff,
                )
                await self._sleep(backoff)
                backoff = min(backoff * 2.0, self._max_backoff_s)
            except Exception:
                logger.exception(
                    "Identity Redis subscriber crashed unexpectedly; retrying with backoff",
                    backoff_s=backoff,
                )
                await self._sleep(backoff)
                backoff = min(backoff * 2.0, self._max_backoff_s)

    async def _run_once(self) -> None:
        """Open one Redis pub/sub session and consume until error or stop."""
        client = self._redis_factory()
        pubsub = client.pubsub()
        await pubsub.psubscribe(IDENTITY_PATTERN)
        logger.info("Identity Redis subscriber attached", pattern=IDENTITY_PATTERN)
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
                await pubsub.punsubscribe(IDENTITY_PATTERN)
                await pubsub.aclose()
            except Exception:
                logger.debug("Error closing identity pubsub", exc_info=True)

    def _handle_raw_message(self, raw: object) -> None:
        """Decode and dispatch a single pub/sub payload, tolerating decode errors."""
        if not isinstance(raw, (bytes, str)):
            logger.warning(
                "Identity envelope payload has unexpected type",
                payload_type=type(raw).__name__,
            )
            return
        try:
            envelope = decode_envelope(raw)
        except MalformedIdentityEnvelopeError as exc:
            logger.warning("Malformed identity envelope; dropping", error=str(exc))
            return
        self.process_envelope(envelope)
