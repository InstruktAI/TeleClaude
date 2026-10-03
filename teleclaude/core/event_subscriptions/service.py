"""Session-owned event-subscription state and delivery."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from instrukt_ai_logging import get_logger
from pydantic import JsonValue

from teleclaude.caller_identity import caller_from_principal, identity_for_session
from teleclaude.core.control_delivery import handoff_control_payload
from teleclaude.core.db_models import EventSubscriptionRow
from teleclaude.core.event_subscription_mode import EventSubscriptionMode
from teleclaude.core.inbound_errors import SessionMessageRejectedError, SessionMessageRejectionReason
from teleclaude.core.injected_text import EnvelopeName, SemanticEnvelope, semantic_envelope
from teleclaude.core.models import Session
from teleclaude.events.envelope import EventEnvelope, subject_owner_token, subject_token
from teleclaude.identity_reach import ReachCache

from .matching import (
    is_after_created_position,
    matches_company,
    matches_narrowing,
    matches_visibility,
)
from .wake import render_wake_body

logger = get_logger(__name__)

_SUBSCRIPTION_ID_PREFIX = "event-subscription:"
_SOURCE_KEY_SEPARATOR = ":"
_DELIVERED_EVENT = "event_subscription_delivered"
_SKIPPED_CLAIMED_EVENT = "event_subscription_skipped_claimed"
_SESSION_CLOSED_REMOVED_EVENT = "event_subscription_session_closed_removed"
_SUBSCRIPTION_CREATED_EVENT = "event_subscription_created"
_SUBSCRIPTION_WITHDRAWN_EVENT = "event_subscription_withdrawn"
_SESSION_SUBSCRIPTIONS_REMOVED_EVENT = "event_subscriptions_session_removed"
_SUBSCRIPTIONS_REBUILT_EVENT = "event_subscriptions_rebuilt"
_PRINCIPAL_REQUIRED_ERROR = "event subscriptions require a resolvable session principal"
_INVALID_NARROWING_OBJECT_ERROR = "event subscription narrowing must be a JSON object"
_JSON_SEPARATORS = (",", ":")


class EventSubscriptionStore(Protocol):
    """Durable operations required by the subscription service."""

    async def insert_event_subscription(self, row: EventSubscriptionRow) -> None: ...

    async def list_event_subscriptions_for_session(self, session_id: str) -> list[EventSubscriptionRow]: ...

    async def list_all_event_subscriptions(self) -> list[EventSubscriptionRow]: ...

    async def delete_event_subscription(self, subscription_id: str, session_id: str) -> bool: ...

    async def delete_event_subscriptions_for_session(self, session_id: str) -> list[str]: ...

    async def claim_event_subscription(self, subscription_id: str, event_id: str) -> bool: ...

    async def delete_event_subscription_by_id(self, subscription_id: str) -> bool: ...

    async def delete_event_subscriptions_for_closed_sessions(self) -> list[str]: ...


class ControlHandoff(Protocol):
    """The control-delivery seam used to persist and wake one session."""

    async def __call__(
        self,
        *,
        session_id: str,
        body: str,
        source_key: str,
        envelope: SemanticEnvelope,
    ) -> object: ...


class EventSubscriptionService:
    """Own subscription records, matching, reach checks and wake handoff."""

    def __init__(
        self,
        store: EventSubscriptionStore,
        stream_position: Callable[[], Awaitable[str]],
        computer_name: str,
        *,
        handoff: ControlHandoff = handoff_control_payload,
    ) -> None:
        self._store = store
        self._stream_position = stream_position
        self._computer_name = computer_name
        self._handoff = handoff
        self._subscriptions_by_event: dict[str, dict[str, EventSubscriptionRow]] = defaultdict(dict)
        self._reach_caches: dict[str, ReachCache] = {}
        self._index_lock = asyncio.Lock()

    async def subscribe(
        self,
        session: Session,
        event_type: str,
        mode: EventSubscriptionMode,
        narrowing: dict[str, JsonValue],
    ) -> EventSubscriptionRow:
        """Create a durable subscription beginning at the current stream tail."""
        principal = identity_for_session(session).principal
        if principal is None:
            raise ValueError(_PRINCIPAL_REQUIRED_ERROR)
        async with self._index_lock:
            row = EventSubscriptionRow(
                id=uuid4().hex,
                session_id=session.session_id,
                event_type=event_type,
                mode=mode.value,
                narrowing_json=json.dumps(narrowing, sort_keys=True, separators=_JSON_SEPARATORS, ensure_ascii=False),
                created_position=await self._stream_position(),
                principal=principal,
                company=session.company,
                claimed_event_id=None,
                created_at=datetime.now(UTC).isoformat(),
            )
            await self._store.insert_event_subscription(row)
            self._subscriptions_by_event[event_type][row.id] = row
        logger.info(
            _SUBSCRIPTION_CREATED_EVENT,
            subscription_id=row.id,
            session_id=row.session_id,
            event_type=row.event_type,
            mode=row.mode,
        )
        return row

    async def list_for(self, session_id: str) -> list[EventSubscriptionRow]:
        """List the live subscriptions owned by one session."""
        return await self._store.list_event_subscriptions_for_session(session_id)

    async def unsubscribe(self, session_id: str, subscription_id: str) -> bool:
        """Withdraw a subscription only from its owning session."""
        removed = await self._store.delete_event_subscription(subscription_id, session_id)
        if removed:
            await self._remove_from_index(subscription_id)
            logger.info(
                _SUBSCRIPTION_WITHDRAWN_EVENT,
                subscription_id=subscription_id,
                session_id=session_id,
            )
        return removed

    async def remove_session(self, session_id: str) -> int:
        """Remove every durable and indexed subscription for a closed session."""
        removed_subscription_ids = await self._store.delete_event_subscriptions_for_session(session_id)
        async with self._index_lock:
            for subscriptions in self._subscriptions_by_event.values():
                for subscription_id, row in list(subscriptions.items()):
                    if row.session_id == session_id:
                        del subscriptions[subscription_id]
        if removed_subscription_ids:
            logger.info(
                _SESSION_SUBSCRIPTIONS_REMOVED_EVENT,
                session_id=session_id,
                subscription_ids=removed_subscription_ids,
            )
        return len(removed_subscription_ids)

    async def rebuild(self) -> None:
        """Discard closed-session rows and rebuild the index from durable state."""
        removed_subscription_ids = await self._store.delete_event_subscriptions_for_closed_sessions()
        rows = await self._store.list_all_event_subscriptions()
        async with self._index_lock:
            self._subscriptions_by_event.clear()
            for row in rows:
                self._subscriptions_by_event[row.event_type][row.id] = row
        if removed_subscription_ids or rows:
            logger.info(
                _SUBSCRIPTIONS_REBUILT_EVENT,
                removed_subscription_ids=removed_subscription_ids,
                subscription_ids=[row.id for row in rows],
            )

    async def deliver(self, envelope: EventEnvelope, entry_id: str) -> None:
        """Deliver one trusted stream event to each eligible live subscription."""
        async with self._index_lock:
            candidates = list(self._subscriptions_by_event.get(envelope.event, {}).values())

        for subscription in candidates:
            if not is_after_created_position(entry_id, subscription.created_position):
                continue
            if not matches_visibility(envelope, self._computer_name):
                continue
            if not matches_narrowing(envelope.payload, self._narrowing(subscription)):
                continue
            reach = self._reach_for(subscription.principal).get()
            if not reach.admits(subject_token(envelope.subject), subject_owner_token(envelope.subject_owner), None):
                continue
            if not matches_company(subscription.company, envelope):
                continue

            mode = EventSubscriptionMode(subscription.mode)
            if mode is EventSubscriptionMode.ONCE:
                claimed = await self._store.claim_event_subscription(subscription.id, envelope.event_id)
                if not claimed:
                    logger.info(
                        _SKIPPED_CLAIMED_EVENT,
                        subscription_id=subscription.id,
                        session_id=subscription.session_id,
                        event_id=envelope.event_id,
                    )
                    continue
                subscription.claimed_event_id = envelope.event_id

            try:
                wake_body = render_wake_body(envelope, subscription)
                await self._handoff(
                    session_id=subscription.session_id,
                    body=wake_body,
                    source_key=(_SUBSCRIPTION_ID_PREFIX + subscription.id + _SOURCE_KEY_SEPARATOR + envelope.event_id),
                    envelope=semantic_envelope(EnvelopeName.NOTIFICATION, body=wake_body),
                )
            except SessionMessageRejectedError as exc:
                if exc.reason not in {SessionMessageRejectionReason.CLOSED, SessionMessageRejectionReason.NOT_FOUND}:
                    raise
                await self._store.delete_event_subscription_by_id(subscription.id)
                await self._remove_from_index(subscription.id)
                logger.info(
                    _SESSION_CLOSED_REMOVED_EVENT,
                    subscription_id=subscription.id,
                    session_id=subscription.session_id,
                    event_id=envelope.event_id,
                )
                continue

            logger.info(
                _DELIVERED_EVENT,
                subscription_id=subscription.id,
                session_id=subscription.session_id,
                event_id=envelope.event_id,
            )
            if mode is EventSubscriptionMode.ONCE:
                await self._store.delete_event_subscription_by_id(subscription.id)
                await self._remove_from_index(subscription.id)

    def close(self) -> None:
        """Release declaration-change listeners held by reach caches."""
        for cache in self._reach_caches.values():
            cache.close()
        self._reach_caches.clear()

    async def _remove_from_index(self, subscription_id: str) -> None:
        """Remove one row from its event-type index."""
        async with self._index_lock:
            for event_type, subscriptions in list(self._subscriptions_by_event.items()):
                subscriptions.pop(subscription_id, None)
                if not subscriptions:
                    del self._subscriptions_by_event[event_type]

    def _reach_for(self, principal: str) -> ReachCache:
        """Return the daemon-lifetime reach cache for one recorded principal."""
        cache = self._reach_caches.get(principal)
        if cache is None:
            cache = ReachCache(caller_from_principal(principal))
            self._reach_caches[principal] = cache
        return cache

    @staticmethod
    def _narrowing(subscription: EventSubscriptionRow) -> dict[str, JsonValue]:
        """Decode one persisted JSON narrowing object."""
        value = json.loads(subscription.narrowing_json)
        if not isinstance(value, dict):
            raise ValueError(_INVALID_NARROWING_OBJECT_ERROR)
        return value
