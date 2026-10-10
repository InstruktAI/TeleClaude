"""Subscribed domain events: the consumer that tells each person every published-domain event their interests select.

A domain event is a fact of its own, so there is no matter to open, close or recover: each event the
computer emitted is composed into one message and told, as it comes, to every person whose notification
interests select its type and whose reach admits its origin. Selection is the interests' (config), the
audience is identity's reach answer per selected person, and the message is the shared notification form;
the consumer decides nothing of its own beyond passing over the platform's own events, which incident
alerts tell. The only state kept is a mark per person told in the event database, so an event handled
again after some sends failed repeats none that were recorded. Sending and recording are not one atomic
act, so delivery is at least once: a send whose recording was interrupted is sent again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.caller_identity import PersonCliCaller
from teleclaude.config.notification_interests import PLATFORM_CATEGORY, selects
from teleclaude.core.integration.notification_messages import compose_notification_message
from teleclaude.core.organization import roster_people
from teleclaude.core.person_messaging import PERSON_DELIVERY_FAILURES, send_person_message
from teleclaude.domains import valid_domains
from teleclaude.events.catalog import EventCatalog
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.db import EventDB
from teleclaude.events.envelope import EventHome, EventHomeOwner, EventHomeRef, EventOwnerRef, ReceivedEvent
from teleclaude.events.type_pattern import ANY_TYPE, TypePattern
from teleclaude.identity_reach import resolve_reach

logger = get_logger(__name__)

SUBSCRIBED_DOMAIN_EVENTS_CONSUMER: Final = "subscribed-domain-events"

_PLATFORM_EVENTS: Final = TypePattern.below(PLATFORM_CATEGORY)
_UNDELIVERED_ERROR: Final = "domain event {event_id} not delivered to {count} recipient(s)"
_DOMAIN_EVENT_TOLD_EVENT: Final = "Domain event told"
_DOMAIN_EVENT_TELL_FAILED_EVENT: Final = "Domain event could not be told"


class DomainEventDeliveryError(RuntimeError):
    """A domain event did not reach every person who awaits it; the runtime retries the handling."""


def _token_or_none(home: EventHome | EventHomeOwner) -> str | None:
    """The subject token of a registered home or owner; none for a marker, which names no registered subject."""
    return home.to_token() if isinstance(home, EventHomeRef | EventOwnerRef) else None


class _SubscribedDomainEvents:
    """The handler of one computer's domain events."""

    def __init__(self, db: EventDB, catalog: EventCatalog) -> None:
        self._db = db
        self._catalog = catalog

    async def handle(self, event: ReceivedEvent) -> None:
        """Tell every person who selects the event and can see its origin, except those already told."""
        if _PLATFORM_EVENTS.matches(event.type) or event.subject is None:
            return
        published = valid_domains()
        selected = [slug for slug, person in roster_people() if selects(person.notifications, event.type, published)]
        origin = _token_or_none(event.home)
        owner = _token_or_none(event.home_owner)
        audience = [
            slug for slug in selected if resolve_reach(PersonCliCaller(person_slug=slug)).admits(origin, owner, None)
        ]
        told = await self._db.get_event_told_recipients(SUBSCRIBED_DOMAIN_EVENTS_CONSUMER, event.id)
        outstanding = [slug for slug in audience if slug not in told]
        if not outstanding:
            return
        text = compose_notification_message(
            event_type=event.type,
            declaration=self._catalog.get(event.type),
            subject=event.subject,
            computer=event.source,
            occurred_at=event.time,
        )
        failed = await self._tell(event, text, outstanding)
        logger.info(_DOMAIN_EVENT_TOLD_EVENT, event_id=event.id, told=len(outstanding) - failed, failed=failed)
        if failed:
            raise DomainEventDeliveryError(_UNDELIVERED_ERROR.format(event_id=event.id, count=failed))

    async def _tell(self, event: ReceivedEvent, text: str, outstanding: list[str]) -> int:
        """Send the message to each outstanding person and mark each success; return how many failed.

        One person's channel failing must not hide the others, so a delivery failure is logged and collected,
        never raised here. Any other exception is a defect and propagates with its own meaning. Logs and the
        raised error name the event, counts and failure types, never the people: who awaits an event is the event's audience
        minus its told marks.
        """
        failed = 0
        for slug in outstanding:
            try:
                await send_person_message(slug, text)
            except PERSON_DELIVERY_FAILURES as exc:
                # The failure's message can carry the recipient's slug or address, so only its type is recorded.
                logger.error(_DOMAIN_EVENT_TELL_FAILED_EVENT, event_id=event.id, error_type=type(exc).__name__)
                failed += 1
                continue
            await self._db.mark_event_told(SUBSCRIBED_DOMAIN_EVENTS_CONSUMER, event.id, slug, datetime.now(UTC))
        return failed


def build_subscribed_domain_events_consumer(db: EventDB, catalog: EventCatalog) -> Consumer:
    """The consumer that tells people about this computer's published-domain events."""
    domain_events = _SubscribedDomainEvents(db, catalog)
    return Consumer(
        name=SUBSCRIBED_DOMAIN_EVENTS_CONSUMER,
        interest=Interest(types=(ANY_TYPE,), own_computer_only=True),
        handler=domain_events.handle,
    )
